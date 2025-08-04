import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import os
import asyncio
from flask import Flask, request
import threading
import random


# ==== CONFIG ====
TOKEN = os.environ["DISCORD_TOKEN"]
MAIN_GUILD_ID = 1371272556820041849
BOD_ROLE_ID = 1371272557034209493
SUPERVISOR_ROLE_IDS = [1371272557034209491, 1371272557034209496]  # Add more if needed
OWNER_IDS = [902727710990811186, 1341152829967958114]
LOGGING_CHANNEL_ID = 1371272557692452884


PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 1400683360623267870
SESSION_CHANNEL_ID = 1396277983211163668
SSU_ROLE_ID = 1371272556820041854
EVENT_ROLE_ID = 1371272556820041853
ANNOUNCEMENT_ROLE_ID = 1371272556820041852
GIVEAWAY_ROLE_ID = 1400878647753048164
REACTION_CHANNEL_ID = 1371272557969281159


LEVEL_ROLE_IDS = {
    1: 1401750387542855710,
    5: 1401750539229728919,
    10: 1401750605822824478,
    20: 1401750676911947837,
}


# Flask setup for keep-alive
app = Flask(__name__)


@app.route('/')
def home():
    return "Bot is alive."


def run_flask():
    app.run(host="0.0.0.0", port=8080)


flask_thread = threading.Thread(target=run_flask)
flask_thread.start()


intents = discord.Intents.default()
intents.members = True
intents.message_content = False  # We do not need message content for now


bot = commands.Bot(command_prefix="!", intents=intents)


# In-memory leveling storage (replace with DB in future)
user_message_counts = {}


# Giveaway storage (in-memory)
active_giveaways = {}  # giveaway_id : giveaway_data


def is_staff(interaction: discord.Interaction):
    roles = [role.id for role in interaction.user.roles]
    return BOD_ROLE_ID in roles or any(r in SUPERVISOR_ROLE_IDS for r in roles)


def is_bod(interaction: discord.Interaction):
    return any(role.id == BOD_ROLE_ID for role in interaction.user.roles)


def is_owner(user_id: int):
    return user_id in OWNER_IDS


async def log_command_use(interaction: discord.Interaction, command_name: str):
    channel = bot.get_channel(LOGGING_CHANNEL_ID)
    if channel:
        await channel.send(f"**{interaction.user}** used command **/{command_name}** in {interaction.channel.mention}")


# ---- STAFF COMMANDS ----
class StaffCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="promote", description="Promote a staff member")
    @app_commands.check(is_bod)
    @app_commands.describe(user="Staff member to promote", new_rank="New rank", reason="Reason for promotion")
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_rank: str, reason: str):
        embed = discord.Embed(
            title="📈 Staff Promotion",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="New Rank", value=new_rank, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Promoted By", value=interaction.user.mention, inline=True)
        channel = interaction.guild.get_channel(PROMOTION_CHANNEL_ID)
        await channel.send(content=user.mention, embed=embed)  # ping promoted user
        await interaction.response.send_message("Promotion logged and user pinged.", ephemeral=True)
        await log_command_use(interaction, "promote")


    @app_commands.command(name="infract", description="Issue an infraction to a staff member")
    @app_commands.check(is_bod)
    @app_commands.describe(user="Staff member to infract", reason="Reason", punishment="Punishment", expires="Expiry (optional)")
    async def infract(self, interaction: discord.Interaction, user: discord.Member, reason: str, punishment: str, expires: str = "N/A"):
        embed = discord.Embed(
            title="⚠️ Staff Infraction",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Punishment", value=punishment, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Issued By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Expires", value=expires, inline=True)
        channel = interaction.guild.get_channel(INFRACTION_CHANNEL_ID)
        await channel.send(content=user.mention, embed=embed)  # ping infracted user
        await interaction.response.send_message("Infraction logged and user pinged.", ephemeral=True)
        await log_command_use(interaction, "infract")


    @app_commands.command(name="serverstart", description="Start a session")
    @app_commands.check(is_bod)
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
            timestamp=datetime.datetime.now()
        )
        await interaction.guild.get_channel(SESSION_CHANNEL_ID).send(content=f"<@&{SSU_ROLE_ID}>", embed=embed)
        await interaction.response.send_message("Session started and SSU pinged.", ephemeral=True)
        await log_command_use(interaction, "serverstart")


    @app_commands.command(name="serverstop", description="End a session")
    @app_commands.check(is_bod)
    async def serverstop(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⛔ Session Ended",
            description=(
                "The server is currently shut down.\n"
                "Please do not join in-game under any circumstances unless told by SHR+\n\n"
                "Please be patient and keep an eye out for our next session here!"
            ),
            color=discord.Color.red(),
            timestamp=datetime.datetime.now()
        )
        await interaction.guild.get_channel(SESSION_CHANNEL_ID).send(embed=embed)
        await interaction.response.send_message("Session ended.", ephemeral=True)
        await log_command_use(interaction, "serverstop")


    @app_commands.command(name="embed", description="Send a custom embed")
    @app_commands.check(is_bod)
    @app_commands.describe(channel="Target channel", title="Embed title (optional)", description="Embed description")
    async def embed(self, interaction: discord.Interaction, channel: discord.TextChannel, description: str, title: str = None):
        embed = discord.Embed(
            description=description,
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now()
        )
        if title:
            embed.title = title
        await channel.send(embed=embed)
        await interaction.response.send_message(f"Embed sent to {channel.mention}", ephemeral=True)
        await log_command_use(interaction, "embed")


    @app_commands.command(name="suggest", description="Make a suggestion (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(
        name="Your name (or leave blank for anonymous)",
        title="Suggestion title",
        description="Suggestion details",
        image_url="Image URL (optional)"
    )
    async def suggest(self, interaction: discord.Interaction, title: str, description: str, name: str = None, image_url: str = None):
        display_name = name if name else "Anonymous"
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now()
        )
        embed.set_footer(text=f"Suggested by {display_name}")
        if image_url:
            embed.set_image(url=image_url)


        suggestions_channel = interaction.guild.get_channel(LOGGING_CHANNEL_ID)  # or separate channel if you want
        suggestion_msg = await suggestions_channel.send(embed=embed)
        thread = await suggestion_msg.create_thread(name=f"Discussion - {title}", auto_archive_duration=1440)
        await interaction.response.send_message("Suggestion submitted and thread created.", ephemeral=True)
        await log_command_use(interaction, "suggest")


# ---- REPORT COMMAND (anyone can use, sends DM to owners only) ----
class ReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="report", description="Report a staff member anonymously")
    @app_commands.describe(
        user="Staff member to report",
        reason="Reason for report"
    )
    async def report(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        dm_text = (
            f"Anonymous report received:\n"
            f"Reported user: {user} ({user.id})\n"
            f"Reason: {reason}\n"
            f"Reporter: {interaction.user} ({interaction.user.id})"
        )
        for owner_id in OWNER_IDS:
            owner = self.bot.get_user(owner_id)
            if owner:
                try:
                    await owner.send(dm_text)
                except:
                    pass
        await interaction.response.send_message("Your report has been sent to the owner(s). Thank you.", ephemeral=True)
        await log_command_use(interaction, "report")


# ---- LEVELING SYSTEM ----
class LevelingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.level_up_messages = {}


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return
        if message.guild.id != MAIN_GUILD_ID:
            return


        user_id = message.author.id
        user_message_counts[user_id] = user_message_counts.get(user_id, 0) + 1
        count = user_message_counts[user_id]


        # Check level ups
        for level in sorted(LEVEL_ROLE_IDS.keys(), reverse=True):
            if count >= level:
                role = message.guild.get_role(LEVEL_ROLE_IDS[level])
                if role not in message.author.roles:
                    try:
                        await message.author.add_roles(role)
                        await message.channel.send(f"🎉 Congrats {message.author.mention}, you've leveled up to level {level}!")
                    except:
                        pass
                break


# ---- GIVEAWAY SYSTEM ----
class GiveawayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_giveaways = {}  # message_id : giveaway_data


    @app_commands.command(name="giveaway", description="Create a giveaway (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(
        channel="Channel to host giveaway",
        prize="Prize description",
        winners="Number of winners",
        duration="Duration (e.g. 10m, 1h, 1d)"
    )
    async def giveaway(self, interaction: discord.Interaction, channel: discord.TextChannel, prize: str, winners: int, duration: str):
        # Parse duration
        seconds = self.parse_duration(duration)
        if seconds is None:
            await interaction.response.send_message("Invalid duration format. Use 10m, 1h, 1d, etc.", ephemeral=True)
            return
        end_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)


        embed = discord.Embed(
            title="🎉 GIVEAWAY 🎉",
            description=f"Prize: **{prize}**\nHosted by: {interaction.user.mention}\nEnds <t:{int(end_time.timestamp())}:R>",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.utcnow()
        )


        view = GiveawayView(self.bot, winners, end_time, channel.id, prize)
        giveaway_msg = await channel.send(embed=embed, view=view)
        self.active_giveaways[giveaway_msg.id] = {
            "channel_id": channel.id,
            "message_id": giveaway_msg.id,
            "prize": prize,
            "winners": winners,
            "end_time": end_time,
            "participants": set()
        }
        await interaction.response.send_message(f"Giveaway started in {channel.mention}", ephemeral=True)
        await log_command_use(interaction, "giveaway")


    def parse_duration(self, dur_str):
        try:
            unit = dur_str[-1].lower()
            amount = int(dur_str[:-1])
            if unit == "m":
                return amount * 60
            elif unit == "h":
                return amount * 3600
            elif unit == "d":
                return amount * 86400
        except:
            return None


    async def end_giveaway(self, giveaway_id):
        data = self.active_giveaways.get(giveaway_id)
        if not data:
            return
        channel = self.bot.get_channel(data["channel_id"])
        try:
            message = await channel.fetch_message(data["message_id"])
        except:
            return


        participants = list(data["participants"])
        if len(participants) == 0:
            await channel.send("Giveaway ended with no participants.")
        else:
            winners = random.sample(participants, min(len(participants), data["winners"]))
            winner_mentions = ", ".join(f"<@{w}>" for w in winners)
            await channel.send(f"🎉 Congratulations {winner_mentions}! You won **{data['prize']}**!")
        # Remove giveaway from active
        del self.active_giveaways[giveaway_id]


class GiveawayView(discord.ui.View):
    def __init__(self, bot, winners, end_time, channel_id, prize):
        super().__init__(timeout=None)
        self.bot = bot
        self.winners = winners
        self.end_time = end_time
        self.channel_id = channel_id
        self.prize = prize


    @discord.ui.button(label="Enter Giveaway", style=discord.ButtonStyle.green, custom_id="giveaway_enter")
    async def enter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway_cog = self.bot.get_cog("GiveawayCog")
        if not giveaway_cog:
            await interaction.response.send_message("Giveaway system not found.", ephemeral=True)
            return


        data = giveaway_cog.active_giveaways.get(interaction.message.id)
        if not data:
            await interaction.response.send_message("This giveaway is no longer active.", ephemeral=True)
            return


        if interaction.user.id in data["participants"]:
            await interaction.response.send_message("You already entered this giveaway.", ephemeral=True)
            return


        data["participants"].add(interaction.user.id)
        await interaction.response.send_message("You have entered the giveaway. Good luck!", ephemeral=True)


# ---- REACTION ROLES ----
class ReactionRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)


       @discord.ui.button(label="SSU Ping", style=discord.ButtonStyle.primary, custom_id="rr_ssu")
    async def ssu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await toggle_role(interaction, SSU_ROLE_ID)


    @discord.ui.button(label="Giveaway Ping", style=discord.ButtonStyle.primary, custom_id="rr_giveaway")
    async def giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        await toggle_role(interaction, GIVEAWAY_ROLE_ID)


    @discord.ui.button(label="Announcement Ping", style=discord.ButtonStyle.primary, custom_id="rr_announcement")
    async def announcement(self, interaction: discord.Interaction, button: discord.ui.Button):
        await toggle_role(interaction, ANNOUNCEMENT_ROLE_ID)


    @discord.ui.button(label="Event Ping", style=discord.ButtonStyle.primary, custom_id="rr_event")
    async def event(self, interaction: discord.Interaction, button: discord.ui.Button):
        await toggle_role(interaction, EVENT_ROLE_ID)


async def toggle_role(interaction: discord.Interaction, role_id: int):
    role = interaction.guild.get_role(role_id)
    if role in interaction.user.roles:
        await interaction.user.remove_roles(role)
        await interaction.response.send_message(f"Removed {role.name} role.", ephemeral=True)
    else:
        await interaction.user.add_roles(role)
        await interaction.response.send_message(f"Added {role.name} role.", ephemeral=True)




# ---- BOT EVENTS ----
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


    # Leave unauthorized guilds
    for guild in bot.guilds:
        if guild.id != MAIN_GUILD_ID:
            print(f"Leaving unauthorized guild: {guild.name}")
            await guild.leave()


    # Add cogs
    await bot.add_cog(StaffCog(bot))
    await bot.add_cog(ReportCog(bot))
    await bot.add_cog(LevelingCog(bot))
    await bot.add_cog(GiveawayCog(bot))


    # Sync slash commands to main guild only
    guild = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)


    # Setup reaction roles panel
    view = ReactionRoleView()
    channel = bot.get_channel(REACTION_CHANNEL_ID)
    if channel:
        await channel.purge(limit=5)
        await channel.send("Click the buttons below to get or remove a ping role:", view=view)


@bot.event
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message("An error occurred.", ephemeral=True)
        channel = bot.get_channel(LOGGING_CHANNEL_ID)
        if channel:
            await channel.send(f"Error in command {interaction.command.name}: {error}")


# Run the bot
bot.run(TOKEN)
