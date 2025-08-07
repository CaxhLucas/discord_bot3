import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import os
import random
import asyncio
import json

# ====== CONFIG =======
TOKEN = os.environ["DISCORD_TOKEN"]
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

bot = commands.Bot(command_prefix="!", intents=intents)

def is_staff(interaction: discord.Interaction) -> bool:
    user_roles = [role.id for role in interaction.user.roles]
    return any(role_id in STAFF_ROLE_IDS for role_id in user_roles)

def is_bod(interaction: discord.Interaction) -> bool:
    return BOD_ROLE_ID in [role.id for role in interaction.user.roles]

def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS

def parse_duration(duration_str: str):
    unit = duration_str[-1]
    if not duration_str[:-1].isdigit():
        return None
    amount = int(duration_str[:-1])
    if unit == "m":
        return amount * 60
    elif unit == "h":
        return amount * 3600
    elif unit == "d":
        return amount * 86400
    return None

def load_giveaways():
    if not os.path.isfile(GIVEAWAY_FILE):
        with open(GIVEAWAY_FILE, "w") as f:
            json.dump({}, f)
    with open(GIVEAWAY_FILE, "r") as f:
        try:
            data = json.load(f)
            return data
        except Exception:
            return {}

def save_giveaways(data):
    with open(GIVEAWAY_FILE, "w") as f:
        json.dump(data, f, indent=4)

class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="promote", description="Promote a staff member")
    @app_commands.check(is_staff)
    @app_commands.describe(
        user="The staff member being promoted",
        new_rank="The new rank",
        reason="Reason for promotion"
    )
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_rank: str, reason: str):
        embed = discord.Embed(
            title="📈 Staff Promotion",
            color=discord.Color.green(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="New Rank", value=new_rank, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Promoted By", value=interaction.user.mention, inline=True)
        channel = interaction.guild.get_channel(PROMOTION_CHANNEL_ID)
        await channel.send(content=user.mention, embed=embed)
        await interaction.response.send_message(f"Promotion logged and {user.display_name} has been pinged.", ephemeral=True)

    @app_commands.command(name="infract", description="Issue an infraction to a staff member")
    @app_commands.check(is_staff)
    @app_commands.describe(
        user="The staff member being infracted",
        reason="Reason for the infraction",
        punishment="Type of punishment (e.g., Warning, Strike)",
        expires="(Optional) Expiry date/time or condition"
    )
    async def infract(self, interaction: discord.Interaction, user: discord.Member, reason: str, punishment: str, expires: str = "N/A"):
        embed = discord.Embed(
            title="⚠️ Staff Infraction",
            color=discord.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Punishment", value=punishment, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Issued By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Expires", value=expires, inline=True)
        channel = interaction.guild.get_channel(INFRACTION_CHANNEL_ID)
        await channel.send(content=user.mention, embed=embed)
        await interaction.response.send_message(f"Infraction logged and {user.display_name} has been pinged.", ephemeral=True)

    @app_commands.command(name="serverstart", description="Start a session")
    @app_commands.check(is_staff)
    async def serverstart(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="✅ Session Started",
            description=(
                "The Staff Team has started a session!\n"
                "Please remember to read all of our in-game rules before joining to prevent moderation.\n\n"
                "**Server Name:** Iowa State Roleplay\n"
                "**In-game Code:** vcJJf\n\n"
                "And have a great roleplay experience!"
            ),
            color=discord.Color.green(),
            timestamp=datetime.datetime.utcnow()
        )
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await channel.send(content=f"<@&{SSU_ROLE_ID}>", embed=embed)
        await interaction.response.send_message("Session started and SSU pinged.", ephemeral=True)

    @app_commands.command(name="serverstop", description="End a session")
    @app_commands.check(is_staff)
    async def serverstop(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⛔ Session Ended",
            description=(
                "The server is currently shut down.\n"
                "Please do not join in-game under any circumstances unless told by SHR+\n\n"
                "Please be patient and keep an eye out for our next session here!"
            ),
            color=discord.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await channel.send(embed=embed)
        await interaction.response.send_message("Session ended.", ephemeral=True)

    @app_commands.command(name="embed", description="Send a custom embed to a channel")
    @app_commands.check(is_staff)
    @app_commands.describe(
        channel="Target channel",
        description="Embed description text",
        title="Optional embed title"
    )
    async def embed(self, interaction: discord.Interaction, channel: discord.TextChannel, description: str, title: str = None):
        embed = discord.Embed(
            description=description,
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.utcnow()
        )
        if title:
            embed.title = title
        await channel.send(embed=embed)
        await interaction.response.send_message(f"Embed sent to {channel.mention}", ephemeral=True)

class SayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="say", description="Send a message as the bot")
    @app_commands.describe(
        channel="Channel to send the message in",
        message="The message to send"
    )
    async def say(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        await channel.send(message)
        await interaction.response.send_message(
            f"Message sent to {channel.mention}.", ephemeral=True
        )

class GiveawayView(discord.ui.View):
    def __init__(self, cog, message_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.message_id = message_id

    @discord.ui.button(label="Enter Giveaway", style=discord.ButtonStyle.success, custom_id="giveaway_enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = self.cog.active_giveaways.get(str(self.message_id))
        if giveaway is None or giveaway.get("ended"):
            return await interaction.response.send_message("This giveaway has ended.", ephemeral=True)
        if str(interaction.user.id) in giveaway["participants"]:
            return await interaction.response.send_message("You already entered!", ephemeral=True)
        giveaway["participants"].append(str(interaction.user.id))
        self.cog.persist()
        await interaction.response.send_message("You entered the giveaway!", ephemeral=True)

    @discord.ui.button(label="Show Entrants", style=discord.ButtonStyle.secondary, custom_id="giveaway_show_entrants")
    async def show_entrants(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = self.cog.active_giveaways.get(str(self.message_id))
        if giveaway is None:
            return await interaction.response.send_message("Giveaway not found.", ephemeral=True)
        if not giveaway["participants"]:
            return await interaction.response.send_message("No one has entered yet.", ephemeral=True)
        mentions = []
        for uid in giveaway["participants"]:
            member = interaction.guild.get_member(int(uid))
            if member:
                mentions.append(member.mention)
            else:
                mentions.append(f"<@{uid}>")
        content = "**Entrants:**\n" + "\n".join(mentions)
        await interaction.response.send_message(content, ephemeral=True)

class GiveawayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_giveaways = load_giveaways() # message_id (str): giveaway data

    def persist(self):
        save_giveaways(self.active_giveaways)

    @app_commands.command(name="giveaway", description="Start a giveaway (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(
        channel="Channel to host the giveaway",
        prize="Prize to win",
        winners="Number of winners",
        duration="Duration (e.g., 10m, 1h, 1d)"
    )
    async def giveaway(self, interaction: discord.Interaction, channel: discord.TextChannel, prize: str, winners: int, duration: str):
        duration_seconds = parse_duration(duration)
        if duration_seconds is None:
            return await interaction.response.send_message("Invalid duration format! Use 10m, 1h, 1d etc.", ephemeral=True)
        end_time = int(discord.utils.utcnow().timestamp() + duration_seconds)
        embed = discord.Embed(
            title="🎉 GIVEAWAY 🎉",
            description=f"Prize: **{prize}**\nHosted by: {interaction.user.mention}\nEnds: <t:{end_time}:R>",
            color=discord.Color.purple(),
            timestamp=datetime.datetime.utcnow()
        )
        giveaway_message = await channel.send(embed=embed, view=GiveawayView(self, 0)) # Temporary message_id
        # Update view with correct message id
        view = GiveawayView(self, giveaway_message.id)
        await giveaway_message.edit(view=view)
        self.active_giveaways[str(giveaway_message.id)] = {
            "channel_id": channel.id,
            "prize": prize,
            "winners": winners,
            "end_time": end_time,
            "message_id": giveaway_message.id,
            "participants": [],
            "ended": False,
            "host_id": interaction.user.id,
        }
        self.persist()
        await interaction.response.send_message(f"Giveaway started in {channel.mention}", ephemeral=True)

    @tasks.loop(seconds=30)
    async def giveaway_checker(self):
        now = int(discord.utils.utcnow().timestamp())
        to_end = []
        for msg_id, giveaway in self.active_giveaways.items():
            if not giveaway["ended"] and giveaway["end_time"] <= now:
                to_end.append(msg_id)
        for msg_id in to_end:
            await self.end_giveaway(msg_id)

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.giveaway_checker.is_running():
            self.giveaway_checker.start()
        # Re-add views for un-ended giveaways
        for msg_id, giveaway in self.active_giveaways.items():
            if not giveaway.get("ended"):
                channel = self.bot.get_channel(giveaway["channel_id"])
                if channel:
                    try:
                        message = await channel.fetch_message(int(msg_id))
                        view = GiveawayView(self, int(msg_id))
                        await message.edit(view=view)
                    except Exception:
                        pass

    async def end_giveaway(self, message_id):
        giveaway = self.active_giveaways.get(str(message_id))
        if not giveaway or giveaway.get("ended"):
            return
        channel = self.bot.get_channel(giveaway["channel_id"])
        if not channel:
            return
        try:
            message = await channel.fetch_message(int(message_id))
        except:
            return
        participants = giveaway["participants"]
        winners_count = giveaway["winners"]
        text = ""
        if len(participants) == 0:
            text = f"No participants for giveaway **{giveaway['prize']}**."
        else:
            winner_ids = random.sample(participants, min(winners_count, len(participants)))
            winner_mentions = ", ".join(f"<@{winner}>" for winner in winner_ids)
            text = f"🎉 Congratulations {winner_mentions}! You won **{giveaway['prize']}**!"
        embed = discord.Embed(
            title="🎉 GIVEAWAY ENDED 🎉",
            description=text,
            color=discord.Color.gold(),
            timestamp=datetime.datetime.utcnow()
        )
        await message.edit(embed=embed, view=None)
        self.active_giveaways[str(message_id)]["ended"] = True
        self.persist()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    for guild in bot.guilds:
        if guild.id != MAIN_GUILD_ID:
            print(f"Leaving unauthorized guild: {guild.name}")
            await guild.leave()
    await bot.add_cog(StaffCommands(bot))
    await bot.add_cog(SayCog(bot))
    await bot.add_cog(GiveawayCog(bot))
    # Add other cogs here as needed...

    guild_obj = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild_obj)
    await bot.tree.sync(guild=guild_obj)

bot.run(TOKEN)
