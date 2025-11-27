import discord
from discord.ext import commands
from discord import app_commands
import os
import json
import asyncio


# ===== CONFIG =====
TOKEN = os.environ["DISCORD_TOKEN"]
MAIN_GUILD_ID = 1371272556820041849


BOD_ROLE_ID = 1371272557034209493
SUPERVISOR_ROLE_IDS = [1371272557034209491, 1371272557034209496]
STAFF_ROLES = [BOD_ROLE_ID] + SUPERVISOR_ROLE_IDS


PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 1400683360623267870
SESSION_CHANNEL_ID = 1396277983211163668
SUGGESTION_CHANNEL_ID = 1401761820431355986
SSU_ROLE_ID = 1371272556820041854


OWNER_ID = 1341152829967958114


JSON_TEST_FILE = "test.json"


# ===== INTENTS =====
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True


bot = commands.Bot(command_prefix="!", intents=intents)


# ===== HELPERS =====
def is_staff(interaction: discord.Interaction) -> bool:
    return any(role.id in STAFF_ROLES for role in interaction.user.roles)


def is_bod(interaction: discord.Interaction) -> bool:
    return BOD_ROLE_ID in [role.id for role in interaction.user.roles]


def load_json(filename):
    if not os.path.exists(filename):
        return {}
    with open(filename, "r") as f:
        return json.load(f)


def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)


# ===== STAFF COMMANDS =====
class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="promote", description="Promote a staff member")
    @app_commands.check(is_bod)
    @app_commands.describe(user="Staff member to promote", new_rank="New rank", reason="Reason for promotion")
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_rank: str, reason: str):
        embed = discord.Embed(
            title="📈 Staff Promotion",
            color=discord.Color.green()
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
            color=discord.Color.red()
        )
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


        await interaction.response.send_message(f"Infraction logged and {user.display_name} has been notified.", ephemeral=True)


    @app_commands.command(name="serverstart", description="Start a session")
    @app_commands.check(is_bod)
    async def serverstart(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="✅ Session Started",
            description="The Staff Team has started a session!\n**Server Name:** Iowa State Roleplay\n**In-game Code:** vcJJf",
            color=discord.Color.green()
        )
        embed.set_image(url="https://media.discordapp.net/attachments/1371272559705722978/1405970022463045863/IMG_2908.png")
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await channel.send(content=f"<@&{SSU_ROLE_ID}>", embed=embed)
        await interaction.response.send_message("Session started and SSU pinged.", ephemeral=True)


    @app_commands.command(name="serverstop", description="End a session")
    @app_commands.check(is_bod)
    async def serverstop(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⛔ Session Ended",
            description="The server is currently shut down.\nPlease do not join in-game unless instructed by SHR+.",
            color=discord.Color.red()
        )
        embed.set_image(url="https://media.discordapp.net/attachments/1371272559705722978/1405970022710644796/IMG_2909.png")
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await channel.send(embed=embed)
        await interaction.response.send_message("Session ended.", ephemeral=True)


# ===== PUBLIC COMMANDS =====
class PublicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="suggest", description="Submit a suggestion")
    @app_commands.describe(title="Suggestion title", description="Suggestion details", image_url="Optional image", anonymous="Remain anonymous?")
    async def suggest(self, interaction: discord.Interaction, title: str, description: str, image_url: str = None, anonymous: bool = False):
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.green()
        )
        if image_url:
            embed.set_image(url=image_url)
        author_name = "Anonymous" if anonymous else interaction.user.display_name
        embed.set_footer(text=f"Suggested by {author_name}")
        channel = interaction.guild.get_channel(SUGGESTION_CHANNEL_ID)
        msg = await channel.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await interaction.response.send_message("Your suggestion has been submitted.", ephemeral=True)


# ===== AUTO RESPONDER =====
class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return


        content = message.content.strip().lower()


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


        elif content == "-game":
            await message.delete()
            embed = discord.Embed(
                title="Here is some in-game information!",
                description="Steps to join in-game:\n1. Wait for an SSU.\n2. Open Roblox → Emergency Response: Liberty County.\n3. Click 3 lines → Servers → Join by Code → vcJJf",
                color=discord.Color.blue()
            )
            await message.channel.send(embed=embed)


        elif content == "-apply":
            await message.delete()
            embed = discord.Embed(
                title="📋 Staff Applications",
                description="To apply for staff, please visit <#1371272557969281166> !",
                color=discord.Color.green()
            )
            await message.channel.send(embed=embed)


        elif content == "-help":
            await message.delete()
            embed = discord.Embed(
                title="❓ Need Assistance?",
                description="If you need help, please open a ticket in <#1371272558221066261>.",
                color=discord.Color.blurple()
            )
            await message.channel.send(embed=embed)


# ===== JSON TEST COMMANDS =====
class JsonTestCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="testjson_add", description="Add a key/value to JSON")
    @app_commands.describe(value="Value to add")
    async def testjson_add(self, interaction: discord.Interaction, value: str):
        data = load_json(JSON_TEST_FILE)
        data["last_value"] = value
        save_json(JSON_TEST_FILE, data)
        await interaction.response.send_message(f"Value saved to JSON: {value}", ephemeral=True)


    @app_commands.command(name="testjson_read", description="Read value from JSON")
    async def testjson_read(self, interaction: discord.Interaction):
        data = load_json(JSON_TEST_FILE)
        value = data.get("last_value", "Nothing found")
        await interaction.response.send_message(f"JSON value: {value}", ephemeral=True)


# ===== BOT EVENTS =====
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


    # Add cogs
    await bot.add_cog(StaffCommands(bot))
    await bot.add_cog(PublicCommands(bot))
    await bot.add_cog(AutoResponder(bot))
    await bot.add_cog(JsonTestCog(bot))


    # Sync commands in guild
    guild_obj = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild_obj)
    await bot.tree.sync(guild=guild_obj)
    print("Slash commands synced.")


@bot.event
async def on_guild_join(guild):
    owner = await bot.fetch_user(OWNER_ID)
    await owner.send(f"I was added to a new server: {guild.name} (ID: {guild.id})")
    await guild.leave()


# ===== RUN BOT =====
bot.run(TOKEN)
