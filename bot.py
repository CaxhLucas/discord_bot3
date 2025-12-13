# FULL BOT CODE – JSON REMOVED, STABLE VERSION
# Python 3.12 / discord.py 2.4+

import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import random
from datetime import datetime, timedelta
from collections import deque

# ================= CONFIG =================
TOKEN = os.environ["DISCORD_TOKEN"]
MAIN_GUILD_ID = 1371272556820041849

OWNER_ID = 1341152829967958114

# Roles
BOD_ROLE_ID = 1371272557034209493
SUPERVISOR_ROLE_IDS = [1371272557034209491, 1371272557034209496]
STAFF_ROLES = [BOD_ROLE_ID] + SUPERVISOR_ROLE_IDS

# Channels
PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 1400683360623267870
SESSION_CHANNEL_ID = 1396277983211163668
SUGGESTION_CHANNEL_ID = 1401761820431355986
LOGGING_CHANNEL_ID = 1371272557692452884
BOD_ALERT_CHANNEL_ID = 1443716401176248492
PARTNERSHIP_CHANNEL_ID = 1421873146834718740

SSU_ROLE_ID = 1371272556820041854

SERVER_START_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022463045863/IMG_2908.png"
SERVER_SHUTDOWN_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022710644796/IMG_2909.png"

# Security thresholds
JOIN_THRESHOLD = 3
JOIN_INTERVAL = 60
NEW_ACCOUNT_DAYS = 30
INACTIVE_DAYS = 14

# ================= BOT SETUP =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

recent_joins = deque()

# ================= HELPERS =================
def is_staff(member: discord.Member):
    return any(role.id in STAFF_ROLES for role in member.roles)


def is_bod_member(member: discord.Member):
    return any(role.id == BOD_ROLE_ID for role in member.roles)


async def log_action(text: str):
    ch = bot.get_channel(LOGGING_CHANNEL_ID)
    if ch:
        await ch.send(text)


# ================= STAFF COMMANDS =================
class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="promote", description="Promote a staff member")
    @app_commands.check(lambda i: is_bod_member(i.user))
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_rank: str, reason: str):
        embed = discord.Embed(title="📈 Staff Promotion", color=discord.Color.green())
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="New Rank", value=new_rank)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Promoted By", value=interaction.user.mention)

        ch = interaction.guild.get_channel(PROMOTION_CHANNEL_ID)
        await ch.send(content=user.mention, embed=embed)
        await interaction.response.send_message("Promotion logged.", ephemeral=True)
        await log_action(f"PROMOTION | {interaction.user} -> {user} ({new_rank})")

    @app_commands.command(name="infract", description="Issue a staff infraction")
    @app_commands.check(lambda i: is_bod_member(i.user))
    async def infract(self, interaction: discord.Interaction, user: discord.Member, reason: str, punishment: str):
        case_id = f"INF-{random.randint(100000, 999999)}"
        embed = discord.Embed(title="⚠️ Staff Infraction", color=discord.Color.red())
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="Punishment", value=punishment)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Issued By", value=interaction.user.mention)
        embed.set_footer(text=f"Case ID: {case_id}")

        ch = interaction.guild.get_channel(INFRACTION_CHANNEL_ID)
        await ch.send(content=user.mention, embed=embed)

        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass

        await interaction.response.send_message(f"Infraction issued. Case `{case_id}`", ephemeral=True)
        await log_action(f"INFRACTION | {case_id} | {interaction.user} -> {user}")

    @app_commands.command(name="serverstart")
    @app_commands.check(lambda i: is_bod_member(i.user))
    async def serverstart(self, interaction: discord.Interaction):
        embed = discord.Embed(title="✅ Session Started", color=discord.Color.green())
        embed.description = "A server session has started."
        embed.set_image(url=SERVER_START_BANNER)
        ch = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await ch.send(content=f"<@&{SSU_ROLE_ID}>", embed=embed)
        await interaction.response.send_message("Session started.", ephemeral=True)

    @app_commands.command(name="serverstop")
    @app_commands.check(lambda i: is_bod_member(i.user))
    async def serverstop(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⛔ Session Ended", color=discord.Color.red())
        embed.set_image(url=SERVER_SHUTDOWN_BANNER)
        ch = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await ch.send(embed=embed)
        await interaction.response.send_message("Session stopped.", ephemeral=True)


# ================= PUBLIC =================
class PublicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="suggest")
    async def suggest(self, interaction: discord.Interaction, title: str, description: str):
        embed = discord.Embed(title=title, description=description, color=discord.Color.green())
        embed.set_footer(text=f"Suggested by {interaction.user.display_name}")
        ch = interaction.guild.get_channel(SUGGESTION_CHANNEL_ID)
        msg = await ch.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await interaction.response.send_message("Suggestion submitted.", ephemeral=True)


# ================= AUTO RESPONDER =================
class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = {}

    def on_cooldown(self, user_id, seconds=5):
        now = datetime.utcnow().timestamp()
        if user_id in self.cooldowns and now - self.cooldowns[user_id] < seconds:
            return True
        self.cooldowns[user_id] = now
        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        content = message.content.lower().strip()

        if content.startswith("-inactive"):
            if self.on_cooldown(message.author.id): return
            await message.delete()
            await message.channel.send("⚠️ This ticket will close after 24h of inactivity.")

        elif content == "-game":
            await message.delete()
            await message.channel.send("Game join instructions posted.")

        elif content == "-apply":
            await message.delete()
            await message.channel.send("Apply in #applications")

        elif content == "-help":
            await message.delete()
            await message.channel.send("Open a ticket for help.")

        # Partnership (STAFF ONLY)
        if message.reference and content == "-partnership" and is_staff(message.author):
            try:
                ref = await message.channel.fetch_message(message.reference.message_id)
                ch = bot.get_channel(PARTNERSHIP_CHANNEL_ID)
                await ch.send(
                    f"📨 Partnership Request\n"
                    f"From: {ref.author.mention}\n"
                    f"Representative: {message.author.mention}\n\n"
                    f"{ref.content}"
                )
                await message.add_reaction("✅")
            except Exception:
                await message.add_reaction("❌")

        if message.content.startswith("/"):
            await log_action(f"COMMAND | {message.author} -> {message.content}")

        await bot.process_commands(message)


# ================= SERVER WARNINGS =================
@bot.event
async def on_member_join(member):
    now = datetime.utcnow()
    recent_joins.append(now)
    while recent_joins and (now - recent_joins[0]).seconds > JOIN_INTERVAL:
        recent_joins.popleft()

    ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)

    if (now - member.created_at).days < NEW_ACCOUNT_DAYS:
        await ch.send(f"⚠️ New account joined: {member.mention}")

    if len(recent_joins) >= JOIN_THRESHOLD:
        await ch.send("🚨 Potential raid detected.")


@tasks.loop(hours=24)
async def inactive_staff_check():
    guild = bot.get_guild(MAIN_GUILD_ID)
    ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)
    now = datetime.utcnow()

    for m in guild.members:
        if is_staff(m) and not m.bot:
            if m.joined_at and (now - m.joined_at).days >= INACTIVE_DAYS:
                await ch.send(f"⚠️ Inactive staff: {m.mention}")


# ================= READY =================
@bot.event
async def on_ready():
    await bot.add_cog(StaffCommands(bot))
    await bot.add_cog(PublicCommands(bot))
    await bot.add_cog(AutoResponder(bot))

    await bot.tree.sync(guild=discord.Object(id=MAIN_GUILD_ID))
    inactive_staff_check.start()

    print(f"Logged in as {bot.user}")


@bot.event
async def on_guild_join(guild):
    owner = await bot.fetch_user(OWNER_ID)
    await owner.send(f"Bot added to {guild.name} ({guild.id})")
    await guild.leave()


bot.run(TOKEN)
