import discord
from discord.ext import commands
from discord import app_commands
import datetime
import os
import random
import asyncio

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

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Helper: Check if user is staff
def is_staff(interaction: discord.Interaction) -> bool:
    user_roles = [role.id for role in interaction.user.roles]
    return any(role_id in STAFF_ROLE_IDS for role_id in user_roles)

# Helper: parse durations like 10s, 5m, 1h, 1d
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
        else:
            return None
    except:
        return None

# Message triggers (-inactive, -game, -apply, -help)
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

# Reaction role add
@bot.event
async def on_raw_reaction_add(payload):
    if payload.channel_id != REACTION_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return

    member = guild.get_member(payload.user_id)
    if not member or member.bot:
        return

    emoji = str(payload.emoji)
    if emoji == "📢":
        role = guild.get_role(ANNOUNCEMENT_ROLE_ID)
    elif emoji == "🎉":
        role = guild.get_role(GIVEAWAY_ROLE_ID)
    elif emoji == "📆":
        role = guild.get_role(EVENT_ROLE_ID)
    elif emoji == "🚨":
        role = guild.get_role(SSU_ROLE_ID)
    else:
        role = None

    if role:
        await member.add_roles(role)

# Reaction role remove
@bot.event
async def on_raw_reaction_remove(payload):
    if payload.channel_id != REACTION_CHANNEL_ID:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return

    member = guild.get_member(payload.user_id)
    if not member:
        return

    emoji = str(payload.emoji)
    if emoji == "📢":
        role = guild.get_role(ANNOUNCEMENT_ROLE_ID)
    elif emoji == "🎉":
        role = guild.get_role(GIVEAWAY_ROLE_ID)
    elif emoji == "📆":
        role = guild.get_role(EVENT_ROLE_ID)
    elif emoji == "🚨":
        role = guild.get_role(SSU_ROLE_ID)
    else:
        role = None

    if role:
        await member.remove_roles(role)

# Slash command giveaway
@tree.command(name="giveaway", description="Start a giveaway (staff only)")
@app_commands.describe(prize="Prize to win", duration="Duration like 10s, 5m, 1h, 1d")
async def giveaway(interaction: discord.Interaction, prize: str, duration: str):
    if not is_staff(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    seconds = parse_duration(duration)
    if seconds is None or seconds <= 0:
        await interaction.response.send_message("Invalid duration format. Use 10s, 5m, 1h, or 1d.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🎉 Giveaway Started! 🎉",
        description=f"Prize: **{prize}**\nReact with 🎉 to enter!",
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"Ends in {duration}")
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("🎉")

    await interaction.response.send_message(f"Giveaway started in {interaction.channel.mention}", ephemeral=True)

    await asyncio.sleep(seconds)

    try:
        new_msg = await interaction.channel.fetch_message(msg.id)
    except Exception:
        await interaction.channel.send("Could not fetch the giveaway message to pick a winner.")
        return

    users = []
    for reaction in new_msg.reactions:
        if str(reaction.emoji) == "🎉":
            users = [user async for user in reaction.users() if not user.bot]
            break

    if users:
        winner = random.choice(users)
        await interaction.channel.send(f"🎉 Congratulations {winner.mention}! You won **{prize}**!")
    else:
        await interaction.channel.send(f"No valid entries for the giveaway **{prize}**.")

# Sync commands on startup
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=MAIN_GUILD_ID))
    print(f"Bot is online as {bot.user}")
    print(f"Commands synced for guild {MAIN_GUILD_ID}")

bot.run(TOKEN)
