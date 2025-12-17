import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import asyncio
from datetime import datetime, timedelta
import random

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
LOGGING_CHANNEL_ID = 1371272557692452884
BOD_ALERT_CHANNEL_ID = 1443716401176248492
PARTNERSHIP_CHANNEL_ID = 1421873146834718740
SSU_ROLE_ID = 1371272556820041854

TICKET_CATEGORY_ID = 1450278544008679425
SUPPORT_BANNER = "https://cdn.discordapp.com/attachments/1449498805517942805/1449498852662181888/image.png"

SERVER_START_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022463045863/IMG_2908.png"
SERVER_SHUTDOWN_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022710644796/IMG_2909.png"

OWNER_ID = 1341152829967958114

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
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_rank: str, reason: str):
        embed = discord.Embed(title="📈 Staff Promotion", color=discord.Color.green())
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="New Rank", value=new_rank)
        embed.add_field(name="Reason", value=reason)
        embed.add_field(name="Promoted By", value=interaction.user.mention)
        await interaction.guild.get_channel(PROMOTION_CHANNEL_ID).send(user.mention, embed=embed)
        await interaction.response.send_message("Promotion logged.", ephemeral=True)

    @app_commands.command(name="infract", description="Issue an infraction")
    @app_commands.check(is_bod)
    async def infract(self, interaction: discord.Interaction, user: discord.Member, reason: str, punishment: str):
        code = random.randint(1000, 9999)
        embed = discord.Embed(title=f"⚠️ Staff Infraction - Code {code}", color=discord.Color.red())
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="Reason", value=reason)
        embed.add_field(name="Punishment", value=punishment)
        embed.add_field(name="Issued By", value=interaction.user.mention)
        await interaction.guild.get_channel(INFRACTION_CHANNEL_ID).send(user.mention, embed=embed)
        await interaction.response.send_message("Infraction issued.", ephemeral=True)

# ====== PUBLIC COMMANDS =======
class PublicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="suggest", description="Submit a suggestion")
    async def suggest(self, interaction: discord.Interaction, title: str, description: str):
        embed = discord.Embed(title=title, description=description, color=discord.Color.green())
        embed.set_footer(text=f"Suggested by {interaction.user.display_name}")
        await interaction.guild.get_channel(SUGGESTION_CHANNEL_ID).send(embed=embed)
        await interaction.response.send_message("Suggestion sent.", ephemeral=True)

# ====== AUTO RESPONDER =======
class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        content = message.content.lower().strip()

        if content == "-partnerinfo":
            embed = discord.Embed(color=discord.Color.blurple())
            embed.set_image(url=SUPPORT_BANNER)

            await message.channel.send(
                "Hello! Thank you for Partnering with Iowa State Roleplay. Here are your next steps:\n\n"
                "Please read the <#1396510203532546200>\n"
                "Next, send over your server ad so I can post it in <#1421873146834718740> !\n"
                "Then, please wait for further instructions from our support member!"
            )
            await message.channel.send(embed=embed)

        await bot.process_commands(message)

# ====== TICKET AUTO MESSAGE =======
@bot.event
async def on_guild_channel_create(channel):
    if isinstance(channel, discord.TextChannel) and channel.category_id == TICKET_CATEGORY_ID:
        embed = discord.Embed(
            description=(
                "Hello! Thank you for contacting the Iowa State Roleplay Support Team.\n"
                "Please state the reason for opening the ticket, and a support member will respond when they're available!"
            ),
            color=discord.Color.blurple()
        )
        embed.set_image(url=SUPPORT_BANNER)
        await channel.send(embed=embed)

# ====== BOT READY =======
@bot.event
async def on_ready():
    await bot.add_cog(StaffCommands(bot))
    await bot.add_cog(PublicCommands(bot))
    await bot.add_cog(AutoResponder(bot))

    guild = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)

    print(f"Logged in as {bot.user}")

bot.run(TOKEN)
