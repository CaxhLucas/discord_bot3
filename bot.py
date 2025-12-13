import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import random
from datetime import datetime, timedelta

# ========= CONFIG =========
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
PARTNERSHIP_CHANNEL_ID = 123456789012345678  # <-- replace
SSU_ROLE_ID = 1371272556820041854

OWNER_ID = 1341152829967958114

# ========= INTENTS =========
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ========= PERMISSIONS =========
def is_bod(interaction: discord.Interaction):
    return any(r.id == BOD_ROLE_ID for r in interaction.user.roles)

def is_staff_member(member: discord.Member):
    return any(r.id in STAFF_ROLES for r in member.roles)

# ========= STAFF COMMANDS =========
class Staff(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="infract", description="Issue a staff infraction")
    @app_commands.check(is_bod)
    async def infract(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str,
        punishment: str,
    ):
        case_id = f"INF-{random.randint(100000, 999999)}"

        embed = discord.Embed(
            title="⚠️ Staff Infraction",
            color=discord.Color.red()
        )
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="Punishment", value=punishment, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Issued By", value=interaction.user.mention)
        embed.add_field(name="Case ID", value=case_id)

        channel = interaction.guild.get_channel(INFRACTION_CHANNEL_ID)
        if channel:
            await channel.send(content=user.mention, embed=embed)

        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass

        await interaction.response.send_message(
            f"Infraction issued. Case ID: `{case_id}`",
            ephemeral=True
        )

# ========= PUBLIC COMMANDS =========
class Public(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="suggest", description="Submit a suggestion")
    async def suggest(self, interaction: discord.Interaction, title: str, description: str):
        embed = discord.Embed(title=title, description=description, color=discord.Color.green())
        embed.set_footer(text=f"Suggested by {interaction.user.display_name}")

        channel = interaction.guild.get_channel(SUGGESTION_CHANNEL_ID)
        msg = await channel.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

        await interaction.response.send_message("Suggestion submitted.", ephemeral=True)

# ========= AUTO RESPONSES =========
class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        content = message.content.lower().strip()

        if content.startswith("-inactive"):
            await message.delete()
            mention = message.content.split(maxsplit=1)[1] if len(message.content.split()) > 1 else ""
            embed = discord.Embed(
                title="⚠️ Ticket Inactivity",
                description=f"This ticket will close in 24 hours.\n{mention}",
                color=discord.Color.orange()
            )
            await message.channel.send(embed=embed)

        elif content == "-apply":
            await message.delete()
            await message.channel.send(
                embed=discord.Embed(
                    title="📋 Staff Applications",
                    description="Apply in <#1371272557969281166>",
                    color=discord.Color.green()
                )
            )

        elif content == "-help":
            await message.delete()
            await message.channel.send(
                embed=discord.Embed(
                    title="❓ Need Help?",
                    description="Open a ticket in <#1371272558221066261>",
                    color=discord.Color.blurple()
                )
            )

        elif content == "-game":
            await message.delete()
            await message.channel.send(
                embed=discord.Embed(
                    title="🎮 In-Game Info",
                    description="Join ER:LC → Servers → Join by Code → `vcJJf`",
                    color=discord.Color.blue()
                )
            )

        # Partnership (STAFF ONLY, reply required)
        if message.reference and "-partnership" in content:
            if not is_staff_member(message.author):
                return

            try:
                replied = await message.channel.fetch_message(message.reference.message_id)
            except discord.NotFound:
                return

            channel = bot.get_channel(PARTNERSHIP_CHANNEL_ID)
            if channel:
                await channel.send(
                    f"**Partnership Request**\n"
                    f"From: {replied.author.mention}\n"
                    f"Representative: {message.author.mention}\n\n"
                    f"{replied.content}"
                )

        # Command logging
        if message.content.startswith("/"):
            ch = bot.get_channel(LOGGING_CHANNEL_ID)
            if ch:
                await ch.send(f"{message.author} used `{message.content}`")

        await bot.process_commands(message)

# ========= SERVER WARNINGS =========
JOIN_THRESHOLD = 3
JOIN_INTERVAL = 60
NEW_ACCOUNT_DAYS = 30
recent_joins = []

@bot.event
async def on_member_join(member):
    now = datetime.utcnow()
    recent_joins.append(now)

    if (now - member.created_at).days < NEW_ACCOUNT_DAYS:
        ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)
        if ch:
            await ch.send(f"⚠️ New account joined: {member.mention}")

    recent_joins[:] = [j for j in recent_joins if (now - j).seconds <= JOIN_INTERVAL]
    if len(recent_joins) >= JOIN_THRESHOLD:
        ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)
        if ch:
            await ch.send("🚨 Potential raid detected.")

# ========= INACTIVE STAFF SCAN =========
@tasks.loop(hours=168)
async def inactive_staff_scan():
    guild = bot.get_guild(MAIN_GUILD_ID)
    channel = bot.get_channel(BOD_ALERT_CHANNEL_ID)
    if not guild or not channel:
        return

    cutoff = datetime.utcnow() - timedelta(days=14)

    for member in guild.members:
        if is_staff_member(member) and not member.bot:
            last_msg = None
            for c in guild.text_channels:
                async for m in c.history(limit=200):
                    if m.author.id == member.id:
                        last_msg = m.created_at
                        break
                if last_msg:
                    break

            if not last_msg or last_msg < cutoff:
                await channel.send(f"⚠️ Inactive staff: {member.mention}")

# ========= READY =========
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    await bot.add_cog(Staff(bot))
    await bot.add_cog(Public(bot))
    await bot.add_cog(AutoResponder(bot))

    guild = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)

    inactive_staff_scan.start()
    print("Bot fully ready.")

@bot.event
async def on_guild_join(guild):
    owner = await bot.fetch_user(OWNER_ID)
    await owner.send(f"Added to server: {guild.name} ({guild.id})")
    await guild.leave()

bot.run(TOKEN)
