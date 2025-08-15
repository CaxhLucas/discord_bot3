import discord
from discord.ext import commands
from discord import app_commands
import os

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
LOGGING_CHANNEL_ID = 1371272557692452884
SUGGESTION_CHANNEL_ID = 1401761820431355986

STARTUP_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022463045863/IMG_2908.png"
SHUTDOWN_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022710644796/IMG_2909.png"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ====== HELPERS =======
def is_bod(interaction: discord.Interaction) -> bool:
    return any(role.id == BOD_ROLE_ID for role in interaction.user.roles)

# ====== MESSAGE TRIGGERS =======
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
                "To join in-game:\n"
                "1. Wait for an SSU.\n"
                "2. Open Roblox, search Emergency Response: Liberty County.\n"
                "3. Click the 3 lines in the top right.\n"
                "4. Go to 'servers.'\n"
                "5. Click 'Join by Code.'\n"
                "6. Enter: vcJJf\n"
                "7. Enjoy!"
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
            description="If you need help, please open a ticket in <#1371272558221066261>.",
            color=discord.Color.blurple()
        )
        await message.channel.send(embed=embed)

    await bot.process_commands(message)

# ====== PUBLIC COMMANDS =======
@tree.command(name="suggest", description="Submit a server suggestion")
@app_commands.describe(title="Title of your suggestion", description="Description", image_url="Optional image", anonymous="Post anonymously?")
async def suggest(interaction: discord.Interaction, title: str, description: str, image_url: str = None, anonymous: bool = False):
    embed = discord.Embed(title=title, description=description, color=discord.Color.green())
    if image_url:
        embed.set_image(url=image_url)
    if anonymous:
        name = "Anonymous"
    else:
        name = interaction.user.mention
    embed.set_footer(text=f"Suggested by {name}")

    channel = interaction.guild.get_channel(SUGGESTION_CHANNEL_ID)
    await channel.send(embed=embed)
    await interaction.response.send_message("✅ Suggestion submitted!", ephemeral=True)

@tree.command(name="report", description="Report a staff member anonymously")
@app_commands.describe(report="Describe the issue")
async def report(interaction: discord.Interaction, report: str):
    embed = discord.Embed(title="🚨 Staff Report", description=report, color=discord.Color.red())
    embed.set_footer(text="Anonymous report")
    for owner_id in OWNER_IDS:
        owner = interaction.guild.get_member(owner_id)
        if owner:
            await owner.send(embed=embed)
    await interaction.response.send_message("✅ Your report has been sent to the server owners.", ephemeral=True)

# ====== BOD ONLY COMMANDS =======
@tree.command(name="embled", description="Create a custom embed")
@app_commands.describe(title="Embed title", description="Embed description", color="Hex color (optional)", image_url="Optional image")
async def embled(interaction: discord.Interaction, title: str, description: str, color: str = None, image_url: str = None):
    if not is_bod(interaction):
        await interaction.response.send_message("❌ BOD only.", ephemeral=True)
        return
    hex_color = int(color.strip("#"), 16) if color else 0x3498db
    embed = discord.Embed(title=title, description=description, color=hex_color)
    if image_url:
        embed.set_image(url=image_url)
    await interaction.channel.send(embed=embed)
    await interaction.response.send_message("✅ Embed sent.", ephemeral=True)

@tree.command(name="server_startup", description="Announce server startup")
async def server_startup(interaction: discord.Interaction):
    if not is_bod(interaction):
        await interaction.response.send_message("❌ BOD only.", ephemeral=True)
        return
    embed = discord.Embed(title="🚀 Server Startup", color=discord.Color.green())
    embed.set_image(url=STARTUP_BANNER)
    await interaction.channel.send(embed=embed)
    await interaction.response.send_message("✅ Startup banner sent.", ephemeral=True)

@tree.command(name="server_shutdown", description="Announce server shutdown")
async def server_shutdown(interaction: discord.Interaction):
    if not is_bod(interaction):
        await interaction.response.send_message("❌ BOD only.", ephemeral=True)
        return
    embed = discord.Embed(title="🛑 Server Shutdown", color=discord.Color.red())
    embed.set_image(url=SHUTDOWN_BANNER)
    await interaction.channel.send(embed=embed)
    await interaction.response.send_message("✅ Shutdown banner sent.", ephemeral=True)

# ====== READY EVENT =======
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=MAIN_GUILD_ID))
    print(f"Bot is online as {bot.user}")

bot.run(TOKEN)
