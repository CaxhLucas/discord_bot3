import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import random
from datetime import datetime, timedelta

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
LOGGING_CHANNEL_ID = 1371272557692452884
BOD_ALERT_CHANNEL_ID = 1443716401176248492
PARTNERSHIP_CHANNEL_ID = 1421873146834718740
SSU_ROLE_ID = 1371272556820041854

OWNER_ID = 1341152829967958114

SERVER_START_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022463045863/IMG_2908.png"
SERVER_SHUTDOWN_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022710644796/IMG_2909.png"

# ===== INTENTS =====
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ===== PERMISSION CHECKS =====
def is_staff(member: discord.Member):
    return any(role.id in STAFF_ROLES for role in member.roles)

def is_bod(interaction: discord.Interaction):
    return BOD_ROLE_ID in [r.id for r in interaction.user.roles]

# ===== STAFF COMMANDS =====
class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="promote")
    @app_commands.check(is_bod)
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_rank: str, reason: str):
        embed = discord.Embed(title="📈 Staff Promotion", color=discord.Color.green())
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="New Rank", value=new_rank)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Promoted By", value=interaction.user.mention)

        await interaction.guild.get_channel(PROMOTION_CHANNEL_ID).send(embed=embed)
        await interaction.response.send_message("Promotion logged.", ephemeral=True)

    @app_commands.command(name="infract")
    @app_commands.check(is_bod)
    async def infract(self, interaction: discord.Interaction, user: discord.Member, punishment: str, reason: str):
        case_id = f"ISR-{random.randint(100000,999999)}"
        embed = discord.Embed(title="⚠️ Staff Infraction", color=discord.Color.red())
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="Punishment", value=punishment)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Case ID", value=case_id)
        embed.add_field(name="Issued By", value=interaction.user.mention)

        await interaction.guild.get_channel(INFRACTION_CHANNEL_ID).send(embed=embed)
        await interaction.response.send_message(f"Infraction issued. Case `{case_id}`", ephemeral=True)

    @app_commands.command(name="serverstart")
    @app_commands.check(is_bod)
    async def serverstart(self, interaction: discord.Interaction):
        embed = discord.Embed(title="✅ Session Started", color=discord.Color.green())
        embed.set_image(url=SERVER_START_BANNER)
        await interaction.guild.get_channel(SESSION_CHANNEL_ID).send(f"<@&{SSU_ROLE_ID}>", embed=embed)
        await interaction.response.send_message("Session started.", ephemeral=True)

    @app_commands.command(name="serverstop")
    @app_commands.check(is_bod)
    async def serverstop(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⛔ Session Ended", color=discord.Color.red())
        embed.set_image(url=SERVER_SHUTDOWN_BANNER)
        await interaction.guild.get_channel(SESSION_CHANNEL_ID).send(embed=embed)
        await interaction.response.send_message("Session ended.", ephemeral=True)

# ===== PUBLIC COMMANDS =====
class PublicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="suggest")
    async def suggest(self, interaction: discord.Interaction, title: str, description: str):
        embed = discord.Embed(title=title, description=description, color=discord.Color.green())
        await interaction.guild.get_channel(SUGGESTION_CHANNEL_ID).send(embed=embed)
        await interaction.response.send_message("Suggestion submitted.", ephemeral=True)

# ===== AUTO RESPONDER & LOGGING =====
cooldowns = {}

class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        now = datetime.utcnow()
        last = cooldowns.get(message.author.id)
        if last and (now - last).seconds < 5:
            return
        cooldowns[message.author.id] = now

        # Partnership (STAFF ONLY)
        if message.reference and message.content.lower() == "-partnership":
            if not is_staff(message.author):
                return

            try:
                replied = await message.channel.fetch_message(message.reference.message_id)
                channel = self.bot.get_channel(PARTNERSHIP_CHANNEL_ID)
                await channel.send(
                    f"📢 **New Partnership Request**\n\n"
                    f"{replied.content}\n\n"
                    f"**Partner:** {replied.author.mention}\n"
                    f"**Representative:** {message.author.mention}"
                )
            except:
                pass

        # Log commands & triggers
        log_ch = self.bot.get_channel(LOGGING_CHANNEL_ID)
        if log_ch:
            await log_ch.send(f"{message.author.mention}: `{message.content}`")

        await self.bot.process_commands(message)

# ===== SERVER WARNINGS =====
JOIN_THRESHOLD = 3
JOIN_INTERVAL = 60
NEW_ACCOUNT_DAYS = 30
recent_joins = []

@bot.event
async def on_member_join(member):
    now = datetime.utcnow()
    recent_joins.append(now)
    recent_joins[:] = [t for t in recent_joins if (now - t).seconds <= JOIN_INTERVAL]

    alert = bot.get_channel(BOD_ALERT_CHANNEL_ID)

    if (now - member.created_at).days < NEW_ACCOUNT_DAYS:
        await alert.send(f"⚠️ New account joined: {member.mention}")

    if len(recent_joins) >= JOIN_THRESHOLD:
        await alert.send("🚨 **Possible raid detected**")

# ===== INACTIVE STAFF SCAN =====
@tasks.loop(days=7)
async def inactive_staff_scan():
    guild = bot.get_guild(MAIN_GUILD_ID)
    alert = bot.get_channel(BOD_ALERT_CHANNEL_ID)
    cutoff = datetime.utcnow() - timedelta(days=14)

    for member in guild.members:
        if is_staff(member) and not member.bot:
            if member.joined_at and member.joined_at < cutoff:
                await alert.send(f"⚠️ Inactive staff detected: {member.mention}")

# ===== READY =====
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    await bot.add_cog(StaffCommands(bot))
    await bot.add_cog(PublicCommands(bot))
    await bot.add_cog(AutoResponder(bot))

    guild = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.clear_commands(guild=guild)
    await bot.tree.sync(guild=guild)

    inactive_staff_scan.start()
    print("Slash commands synced.")

# ===== SECURITY =====
@bot.event
async def on_guild_join(guild):
    owner = await bot.fetch_user(OWNER_ID)
    await owner.send(f"Added to unauthorized server: {guild.name}")
    await guild.leave()

bot.run(TOKEN)
