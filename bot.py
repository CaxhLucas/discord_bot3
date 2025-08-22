import discord
from discord.ext import commands
from discord import app_commands
import os
import datetime

# ====== CONFIG =======
TOKEN = os.environ["DISCORD_TOKEN"]
MAIN_GUILD_ID = 1371272556820041849

BOD_ROLE_ID = 1371272557034209493
SUPERVISOR_ROLE_IDS = [1371272557034209491, 1371272557034209496]
STAFF_ROLES = [BOD_ROLE_ID] + SUPERVISOR_ROLE_IDS
OWNER_IDS = [902727710990811186, 1341152829967958114]

PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 1400683360623267870
SESSION_CHANNEL_ID = 1396277983211163668
LOGGING_CHANNEL_ID = 1371272557692452884
SUGGESTION_CHANNEL_ID = 1401761820431355986

SSU_ROLE_ID = 1371272556820041854

SERVER_START_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022463045863/IMG_2908.png"
SERVER_SHUTDOWN_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022710644796/IMG_2909.png"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ====== PERMISSION CHECKS =======
def is_staff(interaction: discord.Interaction) -> bool:
    return any(role.id in STAFF_ROLES for role in interaction.user.roles)

def is_bod(interaction: discord.Interaction) -> bool:
    return BOD_ROLE_ID in [role.id for role in interaction.user.roles]

# ====== STAFF COMMANDS =======
class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="promote", description="Promote a staff member")
    @app_commands.check(is_bod)
    @app_commands.describe(user="Staff member to promote", new_rank="New rank", reason="Reason for promotion")
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_rank: str, reason: str):
        embed = discord.Embed(
            title="📈 Staff Promotion",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="New Rank", value=new_rank, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Promoted By", value=interaction.user.mention, inline=True)
        channel = interaction.guild.get_channel(PROMOTION_CHANNEL_ID)
        await channel.send(content=user.mention, embed=embed)
        await interaction.response.send_message(f"Promotion logged and {user.display_name} has been pinged.", ephemeral=True)

    @app_commands.command(name="infract", description="Issue an infraction to a staff member")
@app_commands.check(is_bod)
@app_commands.describe(user="Staff member", reason="Reason", punishment="Punishment", expires="Optional expiry")
async def infract(self, interaction: discord.Interaction, user: discord.Member, reason: str, punishment: str, expires: str = "N/A"):
    embed = discord.Embed(
        title="⚠️ Staff Infraction",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Punishment", value=punishment, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Issued By", value=interaction.user.mention, inline=True)
    embed.add_field(name="Expires", value=expires, inline=True)

    # Send to infraction channel (if visible)
    channel = interaction.guild.get_channel(INFRACTION_CHANNEL_ID)
    if channel:
        try:
            await channel.send(content=user.mention, embed=embed)
        except discord.Forbidden:
            pass  # user might not have permission to see the channel

    # Always DM the staff member
    try:
        await user.send(embed=embed)
    except discord.Forbidden:
        pass  # user may have DMs closed

    await interaction.response.send_message(f"Infraction logged and {user.display_name} has been notified.", ephemeral=True)

    @app_commands.command(name="serverstart", description="Start a session")
    @app_commands.check(is_bod)
    async def serverstart(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="✅ Session Started",
            description=(
                "The Staff Team has started a session!\n"
                "Please remember to read all in-game rules before joining.\n\n"
                "**Server Name:** Iowa State Roleplay\n"
                "**In-game Code:** vcJJf"
            ),
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_image(url=SERVER_START_BANNER)
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await channel.send(content=f"<@&{SSU_ROLE_ID}>", embed=embed)
        await interaction.response.send_message("Session started and SSU pinged.", ephemeral=True)

    @app_commands.command(name="serverstop", description="End a session")
    @app_commands.check(is_bod)
    async def serverstop(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⛔ Session Ended",
            description="The server is currently shut down.\nPlease do not join in-game unless instructed by SHR+.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_image(url=SERVER_SHUTDOWN_BANNER)
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await channel.send(embed=embed)
        await interaction.response.send_message("Session ended.", ephemeral=True)

    @app_commands.command(name="say", description="Send a message as the bot")
    @app_commands.check(is_bod)
    @app_commands.describe(channel="Channel", message="Message content")
    async def say(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        await channel.send(message)
        await interaction.response.send_message(f"Message sent to {channel.mention}", ephemeral=True)

    @app_commands.command(name="embled", description="Send a custom embed (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(channel="Target channel", title="Optional title", description="Embed description", image_url="Optional image URL")
    async def embled(self, interaction: discord.Interaction, channel: discord.TextChannel, description: str, title: str = None, image_url: str = None):
        embed = discord.Embed(
            description=description,
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow()
        )
        if title:
            embed.title = title
        if image_url:
            embed.set_image(url=image_url)
        await channel.send(embed=embed)
        await interaction.response.send_message(f"Embed sent to {channel.mention}", ephemeral=True)

# ====== PUBLIC COMMANDS =======
class PublicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="suggest", description="Submit a suggestion")
    @app_commands.describe(title="Suggestion title", description="Suggestion details", image_url="Optional image", anonymous="Remain anonymous?")
    async def suggest(self, interaction: discord.Interaction, title: str, description: str, image_url: str = None, anonymous: bool = False):
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        if image_url:
            embed.set_image(url=image_url)
        author_name = "Anonymous" if anonymous else interaction.user.display_name
        embed.set_footer(text=f"Suggested by {author_name}")
        channel = interaction.guild.get_channel(SUGGESTION_CHANNEL_ID)
        await channel.send(embed=embed)
        await interaction.response.send_message("Your suggestion has been submitted.", ephemeral=True)

    @app_commands.command(name="report", description="Report a staff member")
    @app_commands.describe(message="Report content")
    async def report(self, interaction: discord.Interaction, message: str):
        embed = discord.Embed(
            title="⚠️ Staff Report",
            description=message,
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Reported anonymously")
        for owner_id in OWNER_IDS:
            owner = interaction.guild.get_member(owner_id)
            if owner:
                try:
                    await owner.send(embed=embed)
                except:
                    pass
        await interaction.response.send_message("Your report has been sent to the owners.", ephemeral=True)

# ====== AUTO RESPONDER =======
class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        content = message.content.strip().lower()

        if content.startswith("-"):
            await message.delete()  # delete immediately

        if content == "-inactive":
            embed = discord.Embed(
                title="⚠️ Ticket Inactivity",
                description="This ticket will be automatically closed within 24 hours of inactivity.",
                color=discord.Color.orange()
            )
            await message.channel.send(embed=embed)

        elif content == "-game":
            embed = discord.Embed(
                title="Here is some in-game information!",
                description=(
                    "To join in-game, follow these steps:\n"
                    "1. Make sure to wait for an SSU.\n"
                    "2. Once an SSU has been concurred, open Roblox, search and open Emergency Response: Liberty County.\n"
                    "3. In the top right of the screen, click the 3 lines.\n"
                    "4. Go to \"servers.\"\n"
                    "5. Click \"Join by Code.\"\n"
                    "6. Put in the code \"vcJJf\"\n"
                    "7. And have a great time!"
                ),
                color=discord.Color.blue()
            )
            await message.channel.send(embed=embed)

        elif content == "-apply":
            embed = discord.Embed(
                title="📋 Staff Applications",
                description="To apply for staff, please visit <#1371272557969281166> !",
                color=discord.Color.green()
            )
            await message.channel.send(embed=embed)

        elif content == "-help":
            embed = discord.Embed(
                title="❓ Need Assistance?",
                description="If you're in need of assistance, please open a ticket in <#1371272558221066261>.",
                color=discord.Color.blurple()
            )
            await message.channel.send(embed=embed)

        await bot.process_commands(message)  # ensure commands still work

# ====== BOT EVENTS =======
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    # Add cogs BEFORE syncing commands
    await bot.add_cog(StaffCommands(bot))
    await bot.add_cog(PublicCommands(bot))
    await bot.add_cog(AutoResponder(bot))

    # Register commands in the guild AFTER cogs are added
    guild_obj = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild_obj)
    await bot.tree.sync(guild=guild_obj)

    print("Slash commands synced and ready.")

bot.run(TOKEN)

