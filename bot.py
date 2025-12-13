import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import random
from datetime import datetime, timedelta

# ================= CONFIG =================
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
PARTNERSHIP_CHANNEL_ID = 123456789012345678  # CHANGE
SSU_ROLE_ID = 1371272556820041854

SERVER_START_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022463045863/IMG_2908.png"
SERVER_SHUTDOWN_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022710644796/IMG_2909.png"

OWNER_ID = 1341152829967958114

# ================= INTENTS =================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ================= HELPERS =================
def is_staff(interaction: discord.Interaction) -> bool:
    return any(role.id in STAFF_ROLES for role in interaction.user.roles)

def is_bod(interaction: discord.Interaction) -> bool:
    return BOD_ROLE_ID in [r.id for r in interaction.user.roles]

async def mod_log(guild, message):
    channel = guild.get_channel(LOGGING_CHANNEL_ID)
    if channel:
        await channel.send(message)

def case_id():
    return f"CASE-{random.randint(100000, 999999)}"

# ================= STAFF COMMANDS =================
class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="promote")
    @app_commands.check(is_bod)
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_rank: str, reason: str):
        embed = discord.Embed(title="📈 Staff Promotion", color=discord.Color.green())
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="New Rank", value=new_rank)
        embed.add_field(name="Reason", value=reason)
        embed.add_field(name="By", value=interaction.user.mention)

        ch = interaction.guild.get_channel(PROMOTION_CHANNEL_ID)
        if ch:
            await ch.send(content=user.mention, embed=embed)

        await mod_log(interaction.guild, f"PROMOTION | {user} -> {new_rank} | By {interaction.user}")
        await interaction.response.send_message("Promotion logged.", ephemeral=True)

    @app_commands.command(name="infract")
    @app_commands.check(is_bod)
    async def infract(self, interaction: discord.Interaction, user: discord.Member, punishment: str, reason: str):
        cid = case_id()
        embed = discord.Embed(title="⚠️ Staff Infraction", color=discord.Color.red())
        embed.add_field(name="Case ID", value=cid)
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="Punishment", value=punishment)
        embed.add_field(name="Reason", value=reason)
        embed.add_field(name="Issued By", value=interaction.user.mention)

        ch = interaction.guild.get_channel(INFRACTION_CHANNEL_ID)
        if ch:
            await ch.send(content=user.mention, embed=embed)

        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass

        await mod_log(interaction.guild, f"INFRACTION {cid} | {user} | {punishment}")
        await interaction.response.send_message(f"Infraction issued. Case ID: `{cid}`", ephemeral=True)

    @app_commands.command(name="serverstart")
    @app_commands.check(is_bod)
    async def serverstart(self, interaction: discord.Interaction):
        embed = discord.Embed(title="✅ Session Started", color=discord.Color.green())
        embed.description = "Session is now live."
        embed.set_image(url=SERVER_START_BANNER)

        ch = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        if ch:
            await ch.send(content=f"<@&{SSU_ROLE_ID}>", embed=embed)

        await mod_log(interaction.guild, "SESSION STARTED")
        await interaction.response.send_message("Session started.", ephemeral=True)

    @app_commands.command(name="serverstop")
    @app_commands.check(is_bod)
    async def serverstop(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⛔ Session Ended", color=discord.Color.red())
        embed.set_image(url=SERVER_SHUTDOWN_BANNER)

        ch = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        if ch:
            await ch.send(embed=embed)

        await mod_log(interaction.guild, "SESSION ENDED")
        await interaction.response.send_message("Session ended.", ephemeral=True)

    @app_commands.command(name="say")
    @app_commands.check(is_bod)
    async def say(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        await channel.send(message)
        await interaction.response.send_message("Sent.", ephemeral=True)

    @app_commands.command(name="embled")
    @app_commands.check(is_bod)
    async def embled(self, interaction: discord.Interaction, channel: discord.TextChannel, description: str, title: str = None, image_url: str = None):
        embed = discord.Embed(description=description, color=discord.Color.blurple())
        if title:
            embed.title = title
        if image_url:
            embed.set_image(url=image_url)
        await channel.send(embed=embed)
        await interaction.response.send_message("Embed sent.", ephemeral=True)

# ================= PUBLIC =================
class PublicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="suggest")
    async def suggest(self, interaction: discord.Interaction, title: str, description: str, anonymous: bool = False):
        embed = discord.Embed(title=title, description=description, color=discord.Color.green())
        embed.set_footer(text="Anonymous" if anonymous else interaction.user.display_name)

        ch = interaction.guild.get_channel(SUGGESTION_CHANNEL_ID)
        if ch:
            msg = await ch.send(embed=embed)
            await msg.add_reaction("👍")
            await msg.add_reaction("👎")

        await interaction.response.send_message("Suggestion sent.", ephemeral=True)

# ================= AUTO RESPONDER =================
class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = {}

    def cd(self, user_id, seconds=10):
        now = datetime.utcnow().timestamp()
        if user_id in self.cooldowns and now - self.cooldowns[user_id] < seconds:
            return False
        self.cooldowns[user_id] = now
        return True

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        content = message.content.lower().strip()

        if not self.cd(message.author.id):
            return

        if content == "-inactive":
            await message.delete()
            await message.channel.send(embed=discord.Embed(
                title="⚠️ Inactivity Warning",
                description="This ticket will close in 24 hours if inactive.",
                color=discord.Color.orange()
            ))

        elif content == "-apply":
            await message.delete()
            await message.channel.send("Apply in #applications.")

        elif content == "-help":
            await message.delete()
            await message.channel.send("Open a ticket for help.")

        elif content == "-game":
            await message.delete()
            await message.channel.send("Join instructions posted.")

        # Partnership (staff only, reply based)
        if message.reference and content == "-partnership":
            if not any(r.id in STAFF_ROLES for r in message.author.roles):
                return
            try:
                replied = await message.channel.fetch_message(message.reference.message_id)
                ch = bot.get_channel(PARTNERSHIP_CHANNEL_ID)
                if ch:
                    await ch.send(
                        f"📨 Partnership Request\nFrom: {replied.author.mention}\nRep: {message.author.mention}\nMessage:\n{replied.content}"
                    )
            except:
                pass

        await bot.process_commands(message)

# ================= SECURITY =================
recent_joins = []
JOIN_THRESHOLD = 3
JOIN_INTERVAL = 60
NEW_ACCOUNT_DAYS = 30

@bot.event
async def on_member_join(member):
    now = datetime.utcnow()
    recent_joins.append((member.id, now))

    if (now - member.created_at).days < NEW_ACCOUNT_DAYS:
        ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)
        if ch:
            await ch.send(f"⚠️ New account joined: {member.mention}")

    recent = [j for j in recent_joins if (now - j[1]).seconds <= JOIN_INTERVAL]
    if len(recent) >= JOIN_THRESHOLD:
        ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)
        if ch:
            await ch.send("🚨 Potential raid detected.")

# ================= INACTIVE STAFF =================
@tasks.loop(hours=168)
async def inactive_staff_scan():
    guild = bot.get_guild(MAIN_GUILD_ID)
    if not guild:
        return
    ch = guild.get_channel(BOD_ALERT_CHANNEL_ID)
    for m in guild.members:
        if any(r.id in STAFF_ROLES for r in m.roles) and not m.bot:
            if m.joined_at and (datetime.utcnow() - m.joined_at).days > 14:
                if ch:
                    await ch.send(f"⚠️ Inactive staff: {m.mention}")

# ================= READY =================
@bot.event
async def on_ready():
    await bot.add_cog(StaffCommands(bot))
    await bot.add_cog(PublicCommands(bot))
    await bot.add_cog(AutoResponder(bot))

    guild = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)

    if not inactive_staff_scan.is_running():
        inactive_staff_scan.start()

    print(f"Logged in as {bot.user}")

# ================= SAFETY =================
@bot.event
async def on_guild_join(guild):
    owner = await bot.fetch_user(OWNER_ID)
    await owner.send(f"Added to {guild.name}, leaving.")
    await guild.leave()

bot.run(TOKEN)
