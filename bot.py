import discord
from discord.ext import commands
from discord import app_commands
import os
import json


# ====== CONFIG =======
TOKEN = os.environ["DISCORD_TOKEN"]
MAIN_GUILD_ID = 1371272556820041849


BOD_ROLE_ID = 1371272557034209493
SUPERVISOR_ROLE_IDS = [1371272557034209491, 1371272557034209496]
STAFF_ROLES = [BOD_ROLE_ID] + SUPERVISOR_ROLE_IDS


PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 1400683360623267870
SESSION_CHANNEL_ID = 1396277983211163668
SUGGESTION_CHANNEL_ID = 1401761820431355986
MOD_LOG_CHANNEL_ID = 1371272557692452884
SSU_ROLE_ID = 1371272556820041854


SERVER_START_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022463045863/IMG_2908.png"
SERVER_SHUTDOWN_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022710644796/IMG_2909.png"


OWNER_ID = 1341152829967958114  # For DM when bot joins a new server


INFRACTION_JSON_FILE = "infractions.json"


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


# ====== HELPER FUNCTIONS =======
def load_infractions():
    try:
        with open(INFRACTION_JSON_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_infractions(data):
    with open(INFRACTION_JSON_FILE, "w") as f:
        json.dump(data, f, indent=4)


def log_command(user, command_name, options=None):
    channel = bot.get_channel(MOD_LOG_CHANNEL_ID)
    if channel:
        embed = discord.Embed(title="📝 Command Executed", color=discord.Color.gold())
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Command", value=command_name, inline=True)
        if options:
            opts = "\n".join([f"{k}: {v}" for k, v in options.items()])
            embed.add_field(name="Options", value=opts, inline=False)
        bot.loop.create_task(channel.send(embed=embed))


# ====== STAFF COMMANDS =======
class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="promote", description="Promote a staff member")
    @app_commands.check(is_bod)
    @app_commands.describe(user="Staff member to promote", new_rank="New rank", reason="Reason for promotion")
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_rank: str, reason: str):
        embed = discord.Embed(title="📈 Staff Promotion", color=discord.Color.green())
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="New Rank", value=new_rank, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Promoted By", value=interaction.user.mention, inline=True)
        channel = interaction.guild.get_channel(PROMOTION_CHANNEL_ID)
        await channel.send(content=user.mention, embed=embed)
        await interaction.response.send_message(f"Promotion logged and {user.display_name} has been pinged.", ephemeral=True)
        log_command(interaction.user, "promote", {"user": user.name, "new_rank": new_rank, "reason": reason})


    @app_commands.command(name="infract", description="Issue an infraction to a staff member")
    @app_commands.check(is_bod)
    @app_commands.describe(user="Staff member", reason="Reason", punishment="Punishment", expires="Optional expiry")
    async def infract(self, interaction: discord.Interaction, user: discord.Member, reason: str, punishment: str, expires: str = "N/A"):
        embed = discord.Embed(title="⚠️ Staff Infraction", color=discord.Color.red())
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Punishment", value=punishment, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Issued By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Expires", value=expires, inline=True)


        # Send to infraction channel if visible
        channel = interaction.guild.get_channel(INFRACTION_CHANNEL_ID)
        if channel:
            try:
                await channel.send(content=user.mention, embed=embed)
            except discord.Forbidden:
                pass


        # Always DM the staff member
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass


        # Save to infractions.json
        data = load_infractions()
        user_id = str(user.id)
        if user_id not in data:
            data[user_id] = []
        data[user_id].append({"reason": reason, "punishment": punishment, "issued_by": str(interaction.user.id), "expires": expires})
        save_infractions(data)


        await interaction.response.send_message(f"Infraction logged and {user.display_name} has been notified.", ephemeral=True)
        log_command(interaction.user, "infract", {"user": user.name, "reason": reason, "punishment": punishment, "expires": expires})


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
            color=discord.Color.green()
        )
        embed.set_image(url=SERVER_START_BANNER)
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await channel.send(content=f"<@&{SSU_ROLE_ID}>", embed=embed)
        await interaction.response.send_message("Session started and SSU pinged.", ephemeral=True)
        log_command(interaction.user, "serverstart")


    @app_commands.command(name="serverstop", description="End a session")
    @app_commands.check(is_bod)
    async def serverstop(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⛔ Session Ended",
            description="The server is currently shut down.\nPlease do not join in-game unless instructed by SHR+.",
            color=discord.Color.red()
        )
        embed.set_image(url=SERVER_SHUTDOWN_BANNER)
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await channel.send(embed=embed)
        await interaction.response.send_message("Session ended.", ephemeral=True)
        log_command(interaction.user, "serverstop")


    @app_commands.command(name="say", description="Send a message as the bot")
    @app_commands.check(is_bod)
    @app_commands.describe(channel="Channel", message="Message content")
    async def say(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        await channel.send(message)
        await interaction.response.send_message(f"Message sent to {channel.mention}", ephemeral=True)
        log_command(interaction.user, "say", {"channel": channel.name, "message": message})


    @app_commands.command(name="embled", description="Send a custom embed (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(channel="Target channel", title="Optional title", description="Embed description", image_url="Optional image URL")
    async def embled(self, interaction: discord.Interaction, channel: discord.TextChannel, description: str, title: str = None, image_url: str = None):
        embed = discord.Embed(description=description, color=discord.Color.blurple())
        if title:
            embed.title = title
        if image_url:
            embed.set_image(url=image_url)
        await channel.send(embed=embed)
        await interaction.response.send_message(f"Embed sent to {channel.mention}", ephemeral=True)
        log_command(interaction.user, "embled", {"channel": channel.name, "title": title, "description": description})


# ====== PUBLIC COMMANDS =======
class PublicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="suggest", description="Submit a suggestion")
    @app_commands.describe(title="Suggestion title", description="Suggestion details", image_url="Optional image", anonymous="Remain anonymous?")
    async def suggest(self, interaction: discord.Interaction, title: str, description: str, image_url: str = None, anonymous: bool = False):
        embed = discord.Embed(title=title, description=description, color=discord.Color.green())
        if image_url:
            embed.set_image(url=image_url)
        author_name = "Anonymous" if anonymous else interaction.user.display_name
        embed.set_footer(text=f"Suggested by {author_name}")
        channel = interaction.guild.get_channel(SUGGESTION_CHANNEL_ID)
        msg = await channel.send(embed=embed)
        # Add reaction options
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await interaction.response.send_message("Your suggestion has been submitted.", ephemeral=True)
        log_command(interaction.user, "suggest", {"title": title, "description": description, "anonymous": anonymous})


# ====== AUTO RESPONDER =======
class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return


        content = message.content.strip().lower()


        # ===== Auto Replies =====
        if content.startswith("-inactive"):
            await message.delete()
            parts = message.content.split(maxsplit=1)
            mention_text = parts[1] if len(parts) > 1 else ""
            embed = discord.Embed(
                title="⚠️ Ticket Inactivity",
                description=f"This ticket will be automatically closed within 24 hours of inactivity.\n{mention_text}",
                color=discord.Color.orange()
            )
            await message.channel.send(embed=embed)
            log_command(message.author, "-inactive", {"mention_text": mention_text})


        elif content == "-game":
            await message.delete()
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
            log_command(message.author, "-game")


        elif content == "-apply":
            await message.delete()
            embed = discord.Embed(
                title="📋 Staff Applications",
                description="To apply for staff, please visit <#1371272557969281166> !",
                color=discord.Color.green()
            )
            await message.channel.send(embed=embed)
            log_command(message.author, "-apply")


        elif content == "-help":
            await message.delete()
            embed = discord.Embed(
                title="❓ Need Assistance?",
                description="If you're in need of assistance, please open a ticket in <#1371272558221066261>.",
                color=discord.Color.blurple()
            )
            await message.channel.send(embed=embed)
            log_command(message.author, "-help")


        elif content.startswith("-ship"):
            parts = message.content.split()
            if len(parts) >= 3 and message.mentions and len(message.mentions) >= 2:
                user1 = message.mentions[0]
                user2 = message.mentions[1]
                import random
                percentage = random.randint(0, 100)
                embed = discord.Embed(
                    title="💘 Ship Result",
                    description=f"{user1.mention} and {user2.mention} are **{percentage}%** a match!",
                    color=discord.Color.pink()
                )
                await message.channel.send(embed=embed)
                log_command(message.author, "-ship", {"user1": user1.name, "user2": user2.name, "percentage": percentage})
            else:
                await message.channel.send("Usage: `-ship @user1 @user2`")


# ====== BOT EVENTS =======
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


    # Add cogs
    await bot.add_cog(StaffCommands(bot))
    await bot.add_cog(PublicCommands(bot))
    await bot.add_cog(AutoResponder(bot))


    # Register commands in the guild
    guild_obj = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild_obj)
    await bot.tree.sync(guild=guild_obj)
    print("Slash commands synced.")


@bot.event
async def on_guild_join(guild):
    owner = await bot.fetch_user(OWNER_ID)
    await owner.send(f"I was added to a new server: {guild.name} (ID: {guild.id})")
    await guild.leave()


# ====== LOG SLASH COMMANDS =======
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.application_command:
        options = {o.name: o.value for o in interaction.options} if interaction.options else None
        log_command(interaction.user, interaction.command.name, options)


bot.run(TOKEN)
