import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import asyncio
from datetime import datetime, timezone
import random
import logging
from typing import Any, Dict

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

# In-memory store for detailed log data keyed by the message id the bot posts.
# NOTE: This is in-memory only. Restarting the bot clears stored details.
detailed_logs: Dict[int, Dict[str, Any]] = {}


class ExpandView(discord.ui.View):
    def __init__(self, key: int | None):
        super().__init__(timeout=None)
        # key will be set to the bot log message id after the message is sent
        self.key = key

    @discord.ui.button(label="Expand", style=discord.ButtonStyle.primary, custom_id="expand_button")
    async def expand_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            key = self.key
            if not key:
                await interaction.response.send_message("Details are not available.", ephemeral=True)
                return

            details = detailed_logs.get(key)
            if not details:
                await interaction.response.send_message("Detailed information not available (possibly bot restarted).", ephemeral=True)
                return

            # Build an embed that contains as much detail as available
            detail_embed = discord.Embed(title="Detailed Log Information", color=discord.Color.dark_blue())
            # Add a timestamp if present
            ts = details.get("timestamp")
            if ts:
                detail_embed.set_footer(text=f"Logged at {ts}")

            # Add common fields if present
            common_fields = [
                ("Event Type", details.get("event_type")),
                ("User", details.get("user")),
                ("User ID", details.get("user_id")),
                ("Channel", details.get("channel")),
                ("Channel ID", details.get("channel_id")),
                ("Guild", details.get("guild")),
                ("Guild ID", details.get("guild_id")),
                ("Message ID", details.get("message_id")),
                ("Content", details.get("content")),
                ("Extra", details.get("extra")),
            ]
            for name, val in common_fields:
                if val is not None and val != "":
                    # Limit field length to avoid embed overflow
                    text = str(val)
                    if len(text) > 1024:
                        text = text[:1020] + "..."
                    detail_embed.add_field(name=name, value=text, inline=False)

            # If attachments exist, list them
            attachments = details.get("attachments")
            if attachments:
                att_text = "\n".join(attachments)
                if len(att_text) > 1024:
                    att_text = att_text[:1020] + "..."
                detail_embed.add_field(name="Attachments", value=att_text, inline=False)

            await interaction.response.send_message(embed=detail_embed, ephemeral=True)
        except Exception:
            try:
                await interaction.response.send_message("Failed to retrieve details.", ephemeral=True)
            except Exception:
                pass


# ====== PERMISSION CHECKS =======
def is_staff(interaction: discord.Interaction) -> bool:
    return any(role.id in STAFF_ROLES for role in interaction.user.roles)


def is_bod(interaction: discord.Interaction) -> bool:
    return BOD_ROLE_ID in [role.id for role in interaction.user.roles]


# ====== Helper for sending logs with "Expand" button =======
async def send_embed_with_expand(channel: discord.abc.GuildChannel | discord.TextChannel, embed: discord.Embed, details: Dict[str, Any]):
    """
    Sends an embed to the given channel, attaches an Expand button, and stores the details dict
    keyed by the message id so it can be shown when the button is pressed.
    """
    try:
        view = ExpandView(None)
        sent = await channel.send(embed=embed, view=view)
        # store details keyed by the message id
        details_copy = details.copy()
        # ensure timestamp string exists
        if "timestamp" not in details_copy:
            details_copy["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        detailed_logs[sent.id] = details_copy
        # set the view key to the message id for later lookup
        view.key = sent.id
    except Exception:
        # Silently ignore failures to keep bot stable
        pass


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

        # Command logging for message-based commands and '-' triggers (embed + Expand button)
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

                    details = {
                        "event_type": "message_command",
                        "user": f"{message.author} ({message.author.id})",
                        "user_id": message.author.id,
                        "command": message.content,
                        "content": message.content,
                        "channel": getattr(message.channel, "name", str(message.channel)),
                        "channel_id": getattr(message.channel, "id", None),
                        "guild": getattr(message.guild, "name", None),
                        "guild_id": getattr(message.guild, "id", None),
                        "message_id": message.id,
                        "attachments": [a.url for a in message.attachments] if message.attachments else [],
                        "timestamp": now_str,
                        "extra": None,
                    }
                    # send embed with Expand button and store details
                    await send_embed_with_expand(log_ch, embed, details)

                # Log message-trigger commands that start with '-' (e.g., -inactive, -partnerinfo, -apply, etc.)
                if message.content.startswith("-"):
                    embed = discord.Embed(title="Message Command Used", color=discord.Color.blue())
                    embed.add_field(name="User", value=f"{message.author}", inline=True)
                    embed.add_field(name="Message", value=message.content, inline=True)
                    channel_info = getattr(message.channel, "mention", getattr(message.channel, "name", "Unknown"))
                    embed.add_field(name="Channel", value=channel_info, inline=True)
                    embed.set_footer(text=f"At {now_str}")

                    details = {
                        "event_type": "message_trigger",
                        "user": f"{message.author} ({message.author.id})",
                        "user_id": message.author.id,
                        "content": message.content,
                        "channel": getattr(message.channel, "name", str(message.channel)),
                        "channel_id": getattr(message.channel, "id", None),
                        "guild": getattr(message.guild, "name", None),
                        "guild_id": getattr(message.guild, "id", None),
                        "message_id": message.id,
                        "attachments": [a.url for a in message.attachments] if message.attachments else [],
                        "timestamp": now_str,
                        "extra": None,
                    }
                    await send_embed_with_expand(log_ch, embed, details)
        except Exception:
            # keep logging failures silent
            pass

        await bot.process_commands(message)


# ====== SERVER WARNINGS (with Expand buttons) =======
JOIN_THRESHOLD = 3
JOIN_INTERVAL = 60  # seconds
NEW_ACCOUNT_DAYS = 30
recent_joins = []


@bot.event
async def on_member_join(member):
    now = datetime.now(timezone.utc)
    recent_joins.append((member.id, now))

    # New account detection
    try:
        account_age_days = (now - member.created_at.replace(tzinfo=timezone.utc)).days
    except Exception:
        account_age_days = (now - datetime.now(timezone.utc)).days

    if account_age_days < NEW_ACCOUNT_DAYS:
        channel = bot.get_channel(BOD_ALERT_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="⚠️ New Account Joined",
                description=f"{member.mention} joined. Account is {account_age_days} days old.",
                color=discord.Color.orange()
            )
            details = {
                "event_type": "new_account_join",
                "user": f"{member} ({member.id})",
                "user_id": member.id,
                "content": None,
                "channel": None,
                "channel_id": None,
                "guild": getattr(member.guild, "name", None),
                "guild_id": getattr(member.guild, "id", None),
                "message_id": None,
                "attachments": [],
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "extra": {"created_at": getattr(member, "created_at", None)},
            }
            await send_embed_with_expand(channel, embed, details)

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
            details = {
                "event_type": "raid_detected",
                "user": None,
                "user_id": None,
                "content": None,
                "channel": None,
                "channel_id": None,
                "guild": getattr(member.guild, "name", None),
                "guild_id": getattr(member.guild, "id", None),
                "message_id": None,
                "attachments": [],
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "extra": {"recent_joins": [r[0] for r in recent_joins_filtered]},
            }
            await send_embed_with_expand(channel, embed, details)


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

        # For other channel creations, notify server warnings (BOD_ALERT_CHANNEL_ID) with Expand
        warn_ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)
        if warn_ch:
            embed = discord.Embed(
                title="🔔 Channel Created",
                description=f"Channel {getattr(channel, 'mention', getattr(channel, 'name', str(channel)))} was created in {channel.guild.name}.",
                color=discord.Color.orange()
            )
            details = {
                "event_type": "channel_created",
                "user": None,
                "user_id": None,
                "content": None,
                "channel": getattr(channel, "name", None),
                "channel_id": getattr(channel, "id", None),
                "guild": getattr(channel.guild, "name", None),
                "guild_id": getattr(channel.guild, "id", None),
                "message_id": None,
                "attachments": [],
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "extra": {
                    "category_id": getattr(channel, "category_id", None),
                    "type": str(type(channel)),
                },
            }
            await send_embed_with_expand(warn_ch, embed, details)
    except Exception:
        # avoid crashing on unexpected errors
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
            details = {
                "event_type": "channel_deleted",
                "user": None,
                "user_id": None,
                "content": None,
                "channel": getattr(channel, "name", None),
                "channel_id": getattr(channel, "id", None),
                "guild": getattr(channel.guild, "name", None),
                "guild_id": getattr(channel.guild, "id", None),
                "message_id": None,
                "attachments": [],
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "extra": {"category_id": getattr(channel, "category_id", None)},
            }
            await send_embed_with_expand(warn_ch, embed, details)
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
                details = {
                    "event_type": "channel_updated",
                    "user": None,
                    "user_id": None,
                    "content": None,
                    "channel": getattr(after, "name", None),
                    "channel_id": getattr(after, "id", None),
                    "guild": getattr(after.guild, "name", None),
                    "guild_id": getattr(after.guild, "id", None),
                    "message_id": None,
                    "attachments": [],
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "extra": {
                        "changes": changed,
                        "before": {"name": getattr(before, "name", None), "topic": getattr(before, "topic", None)},
                        "after": {"name": getattr(after, "name", None), "topic": getattr(after, "topic", None)},
                    },
                }
                await send_embed_with_expand(warn_ch, embed, details)
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
            details = {
                "event_type": "role_created",
                "user": None,
                "user_id": None,
                "content": None,
                "channel": None,
                "channel_id": None,
                "guild": getattr(role.guild, "name", None),
                "guild_id": getattr(role.guild, "id", None),
                "message_id": None,
                "attachments": [],
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "extra": {
                    "role_id": getattr(role, "id", None),
                    "permissions": getattr(role, "permissions", None),
                },
            }
            await send_embed_with_expand(warn_ch, embed, details)
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
            details = {
                "event_type": "role_deleted",
                "user": None,
                "user_id": None,
                "content": None,
                "channel": None,
                "channel_id": None,
                "guild": getattr(role.guild, "name", None),
                "guild_id": getattr(role.guild, "id", None),
                "message_id": None,
                "attachments": [],
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "extra": {"role_id": getattr(role, "id", None)},
            }
            await send_embed_with_expand(warn_ch, embed, details)
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
                details = {
                    "event_type": "role_updated",
                    "user": None,
                    "user_id": None,
                    "content": None,
                    "channel": None,
                    "channel_id": None,
                    "guild": getattr(after.guild, "name", None),
                    "guild_id": getattr(after.guild, "id", None),
                    "message_id": None,
                    "attachments": [],
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "extra": {"changes": changes},
                }
                await send_embed_with_expand(warn_ch, embed, details)
    except Exception:
        pass


# Log application (slash) command usage to moderation-logs (embed + Expand button)
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

                    details = {
                        "event_type": "slash_command",
                        "user": f"{interaction.user} ({interaction.user.id})",
                        "user_id": interaction.user.id,
                        "command": f"/{cmd_name}",
                        "content": None,
                        "channel": channel_info,
                        "channel_id": getattr(interaction.channel, "id", None) if interaction.channel else None,
                        "guild": getattr(interaction.guild, "name", None),
                        "guild_id": getattr(interaction.guild, "id", None),
                        "message_id": None,
                        "attachments": [],
                        "timestamp": now_str,
                        "extra": {"interaction_data": interaction.data},
                    }
                    await send_embed_with_expand(ch, embed, details)
            except Exception:
                pass
    except Exception:
        # keep failure silent
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
