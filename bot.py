import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import os
import random
import asyncio
import json

# ====== CONFIG =======
TOKEN = os.environ.get("DISCORD_TOKEN")
MAIN_GUILD_ID = 1371272556820041849

BOD_ROLE_ID = 1371272557034209493
SUPERVISOR_ROLE_IDS = [1371272557034209491, 1371272557034209496]
STAFF_ROLE_IDS = [BOD_ROLE_ID] + SUPERVISOR_ROLE_IDS
OWNER_IDS = [902727710990811186, 1341152829967958114]

PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 1400683360623267870
SESSION_CHANNEL_ID = 1396277983211163668
REACTION_CHANNEL_ID = 1371272557969281159
LOGGING_CHANNEL_ID = 1371272557692452884
SUGGESTION_CHANNEL_ID = 1401761820431355986

SSU_ROLE_ID = 1371272556820041854
EVENT_ROLE_ID = 1371272556820041853
ANNOUNCEMENT_ROLE_ID = 1371272556820041852
GIVEAWAY_ROLE_ID = 1400878647753048164

GIVEAWAY_FILE = "giveaways.json"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ==== HELPERS ====
def is_staff(interaction: discord.Interaction) -> bool:
    return any(role.id in STAFF_ROLE_IDS for role in interaction.user.roles)

def is_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id in OWNER_IDS

def parse_duration(duration_str: str):
    try:
        unit = duration_str[-1].lower()
        amount = int(duration_str[:-1])
        if unit == "s":
            return amount
        elif unit == "m":
            return amount * 60
        elif unit == "h":
            return amount * 3600
        elif unit == "d":
            return amount * 86400
    except Exception:
        return None
    return None

def load_giveaways():
    try:
        with open(GIVEAWAY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_giveaways(data):
    with open(GIVEAWAY_FILE, "w") as f:
        json.dump(data, f, indent=4)

giveaways = load_giveaways()

# ==== MESSAGE TRIGGERS ====
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.lower()

    if content.startswith("-inactive"):
        embed = discord.Embed(
            title="⚠️ Ticket Inactivity",
            description="This ticket will be automatically closed within 24 hours of inactivity",
            color=discord.Color.orange()
        )
        await message.channel.send(embed=embed)

    elif content.startswith("-game"):
        embed = discord.Embed(
            title="Here is some in-game information!",
            description=(
                "To join in-game, follow these steps:\n"
                "1. Make sure to wait for an SSU.\n"
                "2. Once an SSU has been concurred, open Roblox, search and open Emergency Response: Liberty County.\n"
                "3. In the top right of the screen, click the 3 lines.\n"
                "4. Go to 'servers.'\n"
                "5. Click 'Join by Code.'\n"
                "6. Put in the code \"vcJJf\"\n"
                "7. And have a great time!"
            ),
            color=discord.Color.blue()
        )
        await message.channel.send(embed=embed)

    elif content.startswith("-apply"):
        embed = discord.Embed(
            title="Staff Applications",
            description="To apply for staff, please visit <#1371272557969281166> !",
            color=discord.Color.green()
        )
        await message.channel.send(embed=embed)

    elif content.startswith("-help"):
        embed = discord.Embed(
            title="Need Assistance?",
            description="If you're in need of assistance, please open a ticket in <#1371272558221066261> .",
            color=discord.Color.blurple()
        )
        await message.channel.send(embed=embed)

    await bot.process_commands(message)

# ==== GIVEAWAY COMMAND ====
@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(prize="The prize", duration="Duration (e.g. 10s, 5m, 1h, 1d)")
async def giveaway(interaction: discord.Interaction, prize: str, duration: str):
    if not is_staff(interaction):
        await interaction.response.send_message("You do not have permission to start giveaways.", ephemeral=True)
        return

    seconds = parse_duration(duration)
    if seconds is None or seconds < 5:
        await interaction.response.send_message("Invalid duration. Use formats like 10s, 5m, 1h, 1d.", ephemeral=True)
        return

    embed = discord.Embed(title="🎉 Giveaway! 🎉", description=f"Prize: **{prize}**\nReact with 🎉 to enter!", color=discord.Color.gold())
    embed.set_footer(text=f"Ends in {duration}")
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("🎉")

    # Save giveaway info
    giveaways[str(msg.id)] = {
        "channel_id": interaction.channel.id,
        "prize": prize,
        "end_time": int(datetime.datetime.utcnow().timestamp()) + seconds,
        "participants": [],
    }
    save_giveaways(giveaways)

    await interaction.response.send_message("Giveaway started!", ephemeral=True)

# ==== GIVEAWAY REACTION HANDLING ====
@bot.event
async def on_raw_reaction_add(payload):
    if str(payload.message_id) not in giveaways:
        return
    if str(payload.emoji) != "🎉":
        return
    if payload.user_id == bot.user.id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    member = guild.get_member(payload.user_id)
    if not member or member.bot:
        return
    g = giveaways[str(payload.message_id)]
    if payload.user_id not in g["participants"]:
        g["participants"].append(payload.user_id)
        save_giveaways(giveaways)

@tasks.loop(seconds=10)
async def giveaway_check_loop():
    now = int(datetime.datetime.utcnow().timestamp())
    to_remove = []
    for gid, g in giveaways.items():
        if g["end_time"] <= now:
            channel = bot.get_channel(g["channel_id"])
            if not channel:
                to_remove.append(gid)
                continue
            try:
                msg = await channel.fetch_message(int(gid))
            except:
                to_remove.append(gid)
                continue
            participants = g.get("participants", [])
            if not participants:
                await channel.send(f"Giveaway for **{g['prize']}** ended, no entries.")
            else:
                winner_id = random.choice(participants)
                winner = channel.guild.get_member(winner_id)
                winner_mention = winner.mention if winner else f"<@{winner_id}>"
                await channel.send(f"🎉 Congratulations {winner_mention}! You won **{g['prize']}**!")
            to_remove.append(gid)
    for gid in to_remove:
        giveaways.pop(gid, None)
    if to_remove:
        save_giveaways(giveaways)

# ==== REACTION ROLES ====
class ReactionRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RoleToggleButton(ANNOUNCEMENT_ROLE_ID, "📢 Announcement Ping"))
        self.add_item(RoleToggleButton(GIVEAWAY_ROLE_ID, "🎉 Giveaway Ping"))
        self.add_item(RoleToggleButton(EVENT_ROLE_ID, "📆 Event Ping"))
        self.add_item(RoleToggleButton(SSU_ROLE_ID, "🚨 SSU Ping"))

class RoleToggleButton(discord.ui.Button):
    def __init__(self, role_id, label):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("Role not found.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"Removed role {role.name}", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"Added role {role.name}", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user} (ID: {bot.user.id})")
    guild = bot.get_guild(MAIN_GUILD_ID)
    if guild:
        synced = await bot.tree.sync(guild=guild)
        print(f"Synced {len(synced)} commands to guild {guild.name} ({guild.id})")
    else:
        print("Warning: Main guild not found.")
    giveaway_check_loop.start()

    # Send reaction role message if not already present
    channel = bot.get_channel(REACTION_CHANNEL_ID)
    if channel:
        async for msg in channel.history(limit=100):
            if msg.author == bot.user and msg.content == "Click a button below to toggle pings:":
                print("Reaction role message already exists, skipping send.")
                break
        else:
            try:
                view = ReactionRolesView()
                await channel.send("Click a button below to toggle pings:", view=view)
                print("Sent reaction role message.")
            except Exception as e:
                print(f"Failed to send reaction role message: {e}")

bot.run(TOKEN)
