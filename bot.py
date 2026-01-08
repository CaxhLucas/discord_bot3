import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import asyncio
from datetime import datetime, timedelta, timezone
import random
import logging

# ====== CONFIG =======
TOKEN = os.environ["DISCORD_TOKEN"]
MAIN_GUILD_ID = 1371272556820041849

BOD_ROLE_ID = 1371272557034209493
SUPERVISOR_ROLE_IDS = [1371272557034209491, 1371272557034209496]
STAFF_ROLES = [BOD_ROLE_ID] + SUPERVISOR_ROLE_IDS

PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 140068336062326787870
SESSION_CHANNEL_ID = 1396277983211163668
SUGGESTION_CHANNEL_ID = 1401761820431355986
LOGGING_CHANNEL_ID = 1371272557692452884
BOD_ALERT_CHANNEL_ID = 1443716401176248492
PARTNERSHIP_CHANNEL_ID = 1421873146834718740
SSU_ROLE_ID = 1371272556820041854

# New ticket/category and support embed config
TICKET_CATEGORY_ID = 1450278544008679425
SUPPORT_EMBED_BANNER = "https://cdn.discordapp.com/attachments/1449498805517942805/1449498852662181888/image.png"

SERVER_START_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022463045863/IMG_2908.png"
SERVER_SHUTDOWN_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022710644796/IMG_2909.png"

OWNER_ID = 1341152829967958114

# ====== Logging setup =======
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("discord_bot")

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
            color=discord.Color.green()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="New Rank", value=new_rank, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Promoted By", value=interaction.user.mention, inline=True)
        channel = interaction.guild.get_channel(PROMOTION_CHANNEL_ID)
        if channel:
            try:
                await channel.send(content=user.mention, embed=embed)
            except Exception:
                pass
        await interaction.response.send_message(f"Promotion logged and {user.display_name} has been pinged.", ephemeral=True)

    @app_commands.command(name="infract", description="Issue an infraction to a staff member")
    @app_commands.check(is_bod)
    @app_commands.describe(user="Staff member", reason="Reason", punishment="Punishment", expires="Optional expiry")
    async def infract(self, interaction: discord.Interaction, user: discord.Member, reason: str, punishment: str, expires: str = "N/A"):
        code = random.randint(1000, 9999)
        embed = discord.Embed(
            title=f"⚠️ Staff Infraction - Code {code}",
            color=discord.Color.red()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Punishment", value=punishment, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Issued By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Expires", value=expires, inline=True)

        channel = interaction.guild.get_channel(INFRACTION_CHANNEL_ID)
        if channel:
            try:
                await channel.send(content=user.mention, embed=embed)
            except discord.Forbidden:
                pass
            except Exception:
                pass

        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass
        except Exception:
            pass

        await interaction.response.send_message(f"Infraction issued and {user.display_name} has been notified.", ephemeral=True)

    @app_commands.command(name="serverstart", description="Start a session")
    @app_commands.check(is_bod)
    async def serverstart(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="✅ Session Started",
            description="The Staff Team has started a session!\nPlease read all in-game rules before joining.\n**Server Name:** Iowa State Roleplay\n**In-game Code:** vcJJf",
            color=discord.Color.green()
        )
        embed.set_image(url=SERVER_START_BANNER)
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        if channel:
            try:
                await channel.send(content=f"<@&{SSU_ROLE_ID}>", embed=embed)
            except Exception:
                pass
        await interaction.response.send_message("Session started and SSU pinged.", ephemeral=True)

    @app_commands.command(name="serverstop", description="End a session")
    @app_commands.check(is_bod)
    async def serverstop(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⛔ Session Ended",
            description="The server is currently shut down.\nDo not join in-game unless instructed by SHR+.",
            color=discord.Color.red()
        )
        embed.set_image(url=SERVER_SHUTDOWN_BANNER)
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception:
                pass
        await interaction.response.send_message("Session ended.", ephemeral=True)

    @app_commands.command(name="say", description="Send a message as the bot")
    @app_commands.check(is_bod)
    @app_commands.describe(channel="Channel", message="Message content")
    async def say(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        try:
            await channel.send(message)
        except Exception:
            pass
        await interaction.response.send_message(f"Message sent to {channel.mention}", ephemeral=True)

    @app_commands.command(name="embled", description="Send a custom embed (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(channel="Target channel", title="Optional title", description="Embed description", image_url="Optional image URL")
    async def embled(self, interaction: discord.Interaction, channel: discord.TextChannel, description: str, title: str = None, image_url: str = None):
        embed = discord.Embed(description=description, color=discord.Color.blurple())
        if title:
            embed.title = title
        if image_url:
            embed.set_image(url=image_url)
        try:
            await channel.send(embed=embed)
        except Exception:
            pass
        await interaction.response.send_message(f"Embed sent to {channel.mention}", ephemeral=True)

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
        if channel:
            try:
                msg = await channel.send(embed=embed)
                await msg.add_reaction("👍")
                await msg.add_reaction("👎")
            except Exception:
                pass
        await interaction.response.send_message("Your suggestion has been submitted.", ephemeral=True)

    @app_commands.command(name="partnerinfo", description="Information for partners and next steps")
    async def partnerinfo(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🤝 Partnership Information",
            description=(
                "Hello! Thank you for Partnering with Iowa State Roleplay.\n\n"
                "Here are your next steps:\n"
                f"• Please read the <#1396510203532546200>.\n"
                f"• Next, send over your server ad so I can post it in <#1421873146834718740>.\n"
                "• Then, please wait for further instructions from our support member!"
            ),
            color=discord.Color.blue()
        )
        embed.set_image(url=SUPPORT_EMBED_BANNER)
        await interaction.response.send_message(embed=embed, ephemeral=False)

# ====== AUTO RESPONDER =======
class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        content = message.content.strip().lower()

        # Inactive, help, game, apply
        if content.startswith("-inactive"):
            try:
                await message.delete()
            except Exception:
                pass
            parts = message.content.split(maxsplit=1)
            mention_text = parts[1] if len(parts) > 1 else ""
            embed = discord.Embed(
                title="⚠️ Ticket Inactivity",
                description=f"This ticket will be automatically closed within 24 hours of inactivity.\n{mention_text}",
                color=discord.Color.orange()
            )
            try:
                await message.channel.send(embed=embed)
            except Exception:
                pass

        elif content == "-game":
            try:
                await message.delete()
            except Exception:
                pass
            embed = discord.Embed(
                title="Here is some in-game information!",
                description=("Steps to join in-game:\n"
                             "1. Wait for an SSU.\n"
                             "2. Open Roblox, search Emergency Response: Liberty County.\n"
                             "3. Go to servers, join by code: vcJJf"),
                color=discord.Color.blue()
            )
            try:
                await message.channel.send(embed=embed)
            except Exception:
                pass

        elif content == "-apply":
            try:
                await message.delete()
            except Exception:
                pass
            embed = discord.Embed(
                title="📋 Staff Applications",
                description="To apply for staff, please visit <#1371272557969281166>!",
                color=discord.Color.green()
            )
            try:
                await message.channel.send(embed=embed)
            except Exception:
                pass

        elif content == "-help":
            try:
                await message.delete()
            except Exception:
                pass
            embed = discord.Embed(
                title="❓ Need Assistance?",
                description="Open a ticket in <#1371272558221066261>.",
                color=discord.Color.blurple()
            )
            try:
                await message.channel.send(embed=embed)
            except Exception:
                pass

        # Partnership message trigger via -partnerinfo (message command)
        if content == "-partnerinfo":
            try:
                await message.delete()
            except Exception:
                pass
            embed = discord.Embed(
                title="🤝 Partnership Information",
                description=(
                    "Hello! Thank you for Partnering with Iowa State Roleplay.\n\n"
                    "Here are your next steps:\n"
                    "• Please read the <#1396510203532546200>\n"
                    "• Send your server ad so it can be posted in <#1421873146834718740>\n"
                    "• Wait for further instructions from a support member"
                ),
                color=discord.Color.blue()
            )
            embed.set_image(url=SUPPORT_EMBED_BANNER)
            try:
                await message.channel.send(embed=embed)
            except Exception:
                pass

        # Partnership command via reply + -partnership
        if message.reference and "-partnership" in content and any(role.id in STAFF_ROLES for role in message.author.roles):
            try:
                replied_msg = await message.channel.fetch_message(message.reference.message_id)
                partner_channel = bot.get_channel(PARTNERSHIP_CHANNEL_ID)
                if not partner_channel:
                    try:
                        await message.channel.send("Partnership channel not found. Contact an admin.", delete_after=10)
                    except Exception:
                        pass
                    return

                # Determine representative member in the guild
                rep_member = None
                try:
                    if isinstance(replied_msg.author, discord.Member):
                        rep_member = replied_msg.author
                    else:
                        rep_member = message.guild.get_member(replied_msg.author.id)
                except Exception:
                    rep_member = None

                # Duplicate check: look for the representative's ID or mention in recent partnership messages
                is_duplicate = False
                try:
                    async for m in partner_channel.history(limit=500):
                        if rep_member and (str(rep_member.id) in m.content or rep_member.mention in m.content):
                            is_duplicate = True
                            break
                        if replied_msg.content and replied_msg.content in m.content:
                            is_duplicate = True
                            break
                except Exception:
                    is_duplicate = False

                if is_duplicate:
                    try:
                        await message.channel.send("Partnership already exists for that representative in the partnership channel.", delete_after=10)
                    except Exception:
                        pass
                    return

                msg_content = (
                    f"Staff Member: {message.author.mention}\n"
                    f"Representative: {replied_msg.author.mention}\n"
                    f"Content:\n{replied_msg.content}"
                )

                # Send ONLY the required plain text to partnership channel (no embeds, no titles, no extra text)
                try:
                    await partner_channel.send(msg_content)
                except Exception:
                    pass

                # Assign partnership role to the representative (if possible)
                try:
                    partner_role = message.guild.get_role(1392729143375822898)
                    if partner_role and rep_member:
                        await rep_member.add_roles(partner_role, reason=f"Assigned partnership role by {message.author}")
                except discord.Forbidden:
                    pass
                except Exception:
                    pass

                # Intentionally silent on success
            except Exception as e:
                try:
                    await message.channel.send(f"Error logging partnership: {e}", delete_after=10)
                except Exception:
                    pass

        # Command logging for message-based commands and '-' triggers (embed, no pings)
        try:
            log_ch = bot.get_channel(LOGGING_CHANNEL_ID)
            if log_ch:
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

                # Log slash-like messages (starting with '/')
                if message.content.startswith("/"):
                    embed = discord.Embed(title="Command Used", color=discord.Color.blue())
                    embed.add_field(name="User", value=f"{message.author}", inline=True)
                    embed.add_field(name="Command", value=message.content, inline=True)
                    channel_info = getattr(message.channel, "mention", getattr(message.channel, "name", "Unknown"))
                    embed.add_field(name="Channel", value=channel_info, inline=True)
                    embed.set_footer(text=f"At {now_str}")
                    try:
                        await log_ch.send(embed=embed)
                    except Exception:
                        pass

                # Log message-trigger commands that start with '-' (e.g., -inactive, -partnerinfo, -apply, etc.)
                if message.content.startswith("-"):
                    embed = discord.Embed(title="Message Command Used", color=discord.Color.blue())
                    embed.add_field(name="User", value=f"{message.author}", inline=True)
                    embed.add_field(name="Message", value=message.content, inline=True)
                    channel_info = getattr(message.channel, "mention", getattr(message.channel, "name", "Unknown"))
                    embed.add_field(name="Channel", value=channel_info, inline=True)
                    embed.set_footer(text=f"At {now_str}")
                    try:
                        await log_ch.send(embed=embed)
                    except Exception:
                        pass
        except Exception:
            # keep logging failures silent
            pass

        await bot.process_commands(message)

# ====== SERVER WARNINGS =======
JOIN_THRESHOLD = 3
JOIN_INTERVAL = 60  # seconds
NEW_ACCOUNT_DAYS = 30
INACTIVE_DAYS = 14
recent_joins = []

@bot.event
async def on_member_join(member):
    now = datetime.now(timezone.utc)
    recent_joins.append((member.id, now))

    # New account detection
    try:
        account_age_days = (now - member.created_at).days
    except Exception:
        account_age_days = (now - datetime.utcnow()).days

    if account_age_days < NEW_ACCOUNT_DAYS:
        channel = bot.get_channel(BOD_ALERT_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="⚠️ New Account Joined",
                description=f"{member.display_name} ({member.id}) joined. Account is {account_age_days} days old.",
                color=discord.Color.orange()
            )
            try:
                await channel.send(embed=embed)
            except Exception:
                pass

    # Raid detection
    recent_joins_filtered = [j for j in recent_joins if (now - j[1]).total_seconds() <= JOIN_INTERVAL]
    if len(recent_joins_filtered) >= JOIN_THRESHOLD:
        channel = bot.get_channel(BOD_ALERT_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="⚠️ Potential Raid Detected",
                description=f"{len(recent_joins_filtered)} members joined within {JOIN_INTERVAL} seconds.",
                color=discord.Color.red()
            )
            try:
                await channel.send(embed=embed)
            except Exception:
                pass

# Background task: inactive staff scan
@tasks.loop(hours=24)
async def check_inactive_staff():
    await bot.wait_until_ready()
    guild = bot.get_guild(MAIN_GUILD_ID)
    channel = bot.get_channel(BOD_ALERT_CHANNEL_ID)
    now = datetime.now(timezone.utc)
    if not guild or not channel:
        return
    for member in guild.members:
        if any(role.id in STAFF_ROLES for role in member.roles) and not member.bot:
            last_message_time = None
            for text_channel in guild.text_channels:
                try:
                    async for msg in text_channel.history(limit=1000):
                        if msg.author.id == member.id:
                            last_message_time = msg.created_at
                            break
                except Exception:
                    # permission/rate issues: skip channel
                    continue
                if last_message_time:
                    break
            try:
                if not last_message_time or (now - last_message_time).days >= INACTIVE_DAYS:
                    embed = discord.Embed(
                        title="⚠️ Inactive Staff Member",
                        description=f"{member.display_name} ({member.id}) has not sent a message in {INACTIVE_DAYS} days.",
                        color=discord.Color.orange()
                    )
                    try:
                        await channel.send(embed=embed)
                    except Exception:
                        pass
            except Exception:
                continue

# ====== TICKET CHANNEL HANDLING & SERVER WARNING EVENTS =======
@bot.event
async def on_guild_channel_create(channel):
    # When a new text channel is created under the ticket category, send the support welcome embed
    try:
        if isinstance(channel, discord.TextChannel) and channel.category_id == TICKET_CATEGORY_ID:
            welcome_text = (
                "Hello! Thank you for contacting the Iowa State Roleplay Support Team.\n"
                "Please state the reason for opening the ticket, and a support member will respond when they're available!"
            )
            embed = discord.Embed(color=discord.Color.blurple())
            embed.set_image(url=SUPPORT_EMBED_BANNER)
            try:
                await channel.send(content=welcome_text, embed=embed)
            except Exception:
                pass
            return

        # For other channel creations, notify server warnings (BOD_ALERT_CHANNEL_ID)
        warn_ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)
        if warn_ch:
            embed = discord.Embed(
                title="🔔 Channel Created",
                description=f"Channel {getattr(channel, 'mention', getattr(channel, 'name', str(channel)))} was created in {channel.guild.name}.",
                color=discord.Color.orange()
            )
            try:
                await warn_ch.send(embed=embed)
            except Exception:
                pass
    except Exception:
        pass

@bot.event
async def on_guild_channel_delete(channel):
    try:
        warn_ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)
        if warn_ch:
            embed = discord.Embed(
                title="🗑️ Channel Deleted",
                description=f"Channel `{getattr(channel, 'name', 'unknown')}` was deleted in {channel.guild.name}.",
                color=discord.Color.orange()
            )
            try:
                await warn_ch.send(embed=embed)
            except Exception:
                pass
    except Exception:
        pass

@bot.event
async def on_guild_channel_update(before, after):
    try:
        changed = []
        if getattr(before, "name", None) != getattr(after, "name", None):
            changed.append(f"Name: `{before.name}` -> `{after.name}`")
        if getattr(before, "topic", None) != getattr(after, "topic", None):
            changed.append("Topic updated.")
        if changed:
            warn_ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)
            if warn_ch:
                embed = discord.Embed(
                    title="✏️ Channel Updated",
                    description=f"Channel {getattr(after, 'mention', getattr(after, 'name', str(after)))} was updated.\n" + "\n".join(changed),
                    color=discord.Color.orange()
                )
                try:
                    await warn_ch.send(embed=embed)
                except Exception:
                    pass
    except Exception:
        pass

@bot.event
async def on_guild_role_create(role):
    try:
        warn_ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)
        if warn_ch:
            embed = discord.Embed(
                title="➕ Role Created",
                description=f"Role `{role.name}` was created.",
                color=discord.Color.orange()
            )
            try:
                await warn_ch.send(embed=embed)
            except Exception:
                pass
    except Exception:
        pass

@bot.event
async def on_guild_role_delete(role):
    try:
        warn_ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)
        if warn_ch:
            embed = discord.Embed(
                title="🗑️ Role Deleted",
                description=f"Role `{role.name}` was deleted.",
                color=discord.Color.orange()
            )
            try:
                await warn_ch.send(embed=embed)
            except Exception:
                pass
    except Exception:
        pass

@bot.event
async def on_guild_role_update(before, after):
    try:
        changes = []
        if before.name != after.name:
            changes.append(f"Name: `{before.name}` -> `{after.name}`")
        if before.color != after.color:
            changes.append("Color changed.")
        if before.permissions != after.permissions:
            changes.append("Permissions changed.")
        if changes:
            warn_ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)
            if warn_ch:
                embed = discord.Embed(
                    title="✏️ Role Updated",
                    description=f"Role `{after.name}` was updated.\n" + "\n".join(changes),
                    color=discord.Color.orange()
                )
                try:
                    await warn_ch.send(embed=embed)
                except Exception:
                    pass
    except Exception:
        pass

# Log application (slash) command usage to moderation-logs (embed to avoid ping)
@bot.event
async def on_interaction(interaction: discord.Interaction):
    try:
        if interaction.type == discord.InteractionType.application_command:
            cmd_name = ""
            try:
                if isinstance(interaction.data, dict):
                    cmd_name = interaction.data.get("name", "")
            except Exception:
                cmd_name = ""
            try:
                ch = bot.get_channel(LOGGING_CHANNEL_ID)
                if ch:
                    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                    embed = discord.Embed(title="Slash Command Used", color=discord.Color.blue())
                    embed.add_field(name="User", value=f"{interaction.user}", inline=True)
                    embed.add_field(name="Command", value=f"/{cmd_name}", inline=True)
                    channel_info = "DM"
                    try:
                        if interaction.channel:
                            channel_info = getattr(interaction.channel, "mention", getattr(interaction.channel, "name", "Unknown"))
                    except Exception:
                        channel_info = "Unknown"
                    embed.add_field(name="Channel", value=channel_info, inline=True)
                    embed.set_footer(text=f"At {now_str}")
                    try:
                        await ch.send(embed=embed)
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass

# ====== BOT EVENTS =======
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    # prevent duplicate cog registration on reconnect
    if not bot.get_cog("StaffCommands"):
        try:
            await bot.add_cog(StaffCommands(bot))
        except Exception:
            pass
    if not bot.get_cog("PublicCommands"):
        try:
            await bot.add_cog(PublicCommands(bot))
        except Exception:
            pass
    if not bot.get_cog("AutoResponder"):
        try:
            await bot.add_cog(AutoResponder(bot))
        except Exception:
            pass

    guild_obj = discord.Object(id=MAIN_GUILD_ID)
    try:
        bot.tree.copy_global_to(guild=guild_obj)
        await bot.tree.sync(guild=guild_obj)
        logger.info("Slash commands synced.")
    except Exception:
        logger.exception("Failed to sync slash commands")

    check_inactive_staff.start()

@bot.event
async def on_guild_join(guild):
    try:
        owner = await bot.fetch_user(OWNER_ID)
        try:
            await owner.send(f"I was added to a new server: {guild.name} (ID: {guild.id})")
        except Exception:
            # owner DMs blocked or failed
            pass
    except Exception:
        pass
    try:
        await guild.leave()
    except Exception:
        pass

bot.run(TOKEN)
