import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import asyncio
from datetime import datetime, timezone
import random
import logging
from typing import Any, Dict, Optional, List
import json
import re

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

# Mod archive (persistent storage inside Discord)
MOD_ARCHIVE_CHANNEL_ID = 1459286015905890345

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


class ExpandView(discord.ui.View):
    def __init__(self, archive_message_id: int):
        super().__init__(timeout=None)
        # store archive message id in the view for convenience; button custom_id will also carry it
        self.archive_message_id = archive_message_id
        # Add a button whose custom_id encodes the archive message id
        custom_id = f"expand:{archive_message_id}"
        self.add_item(discord.ui.Button(label="Expand", style=discord.ButtonStyle.primary, custom_id=custom_id))


# ====== PERMISSION CHECKS =======
def is_staff(interaction: discord.Interaction) -> bool:
    return any(role.id in STAFF_ROLES for role in interaction.user.roles)


def is_bod(interaction: discord.Interaction) -> bool:
    return BOD_ROLE_ID in [role.id for role in interaction.user.roles]


# ====== Helper utilities =======
async def ensure_channel(channel_id: int) -> Optional[discord.TextChannel]:
    ch = bot.get_channel(channel_id)
    if ch:
        return ch
    try:
        ch = await bot.fetch_channel(channel_id)
        return ch
    except Exception:
        return None


def _extract_json_from_codeblock(content: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON object from a triple-backtick code block (```json\n...\n```) or raw JSON.
    Returns parsed dict or None.
    """
    if not content:
        return None
    content = content.strip()
    # codeblock pattern
    if content.startswith("```") and content.endswith("```"):
        # remove first line fence + optional language and final fence
        lines = content.splitlines()
        if len(lines) >= 3:
            inner = "\n".join(lines[1:-1])
        else:
            inner = ""
    else:
        inner = content
    try:
        return json.loads(inner)
    except Exception:
        # try to find a JSON object inside
        m = re.search(r"\{.*\}", inner, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


async def archive_details_to_mod_channel(details: Dict[str, Any]) -> Optional[int]:
    """
    Post a JSON-encoded details message to the MOD_ARCHIVE_CHANNEL_ID.
    Returns the archive message id or None.
    """
    archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not archive_ch:
        return None
    try:
        details_serializable = json.dumps(details, default=str, ensure_ascii=False, indent=2)
    except Exception:
        details_serializable = json.dumps({k: str(v) for k, v in details.items()}, ensure_ascii=False, indent=2)
    archive_content = f"```json\n{details_serializable}\n```"
    try:
        msg = await archive_ch.send(content=archive_content)
        return msg.id
    except Exception:
        return None


async def send_embed_with_expand(target_channel: discord.abc.GuildChannel | discord.TextChannel, embed: discord.Embed, details: Dict[str, Any]):
    """
    Sends an embed to the given target_channel, creates a detailed storage message in the mod-archive channel,
    then attaches an Expand button to the embed where the button's custom_id references the archive message ID.

    Archive storage is a message posted in MOD_ARCHIVE_CHANNEL_ID containing the JSON-encoded details inside a code block.
    The Expand button custom_id is "expand:{archive_msg.id}" which the on_interaction handler will parse to fetch details.
    """
    try:
        archive_msg_id = await archive_details_to_mod_channel(details)
        archive_id = archive_msg_id or 0
        view = ExpandView(archive_id)
        try:
            await target_channel.send(embed=embed, view=view)
        except Exception:
            # fallback: send without view
            try:
                await target_channel.send(embed=embed)
            except Exception:
                pass
    except Exception:
        pass


async def find_archived_infractions_in_mod(limit: int = 1000) -> List[Dict[str, Any]]:
    """
    Return list of parsed archived detail dicts from MOD_ARCHIVE_CHANNEL_ID (most recent first).
    """
    archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    results: List[Dict[str, Any]] = []
    if not archive_ch:
        return results
    try:
        async for m in archive_ch.history(limit=limit):
            parsed = _extract_json_from_codeblock(m.content or "")
            if parsed:
                # attach archive_message_id for reference
                parsed["_archive_message_id"] = m.id
                results.append(parsed)
    except Exception:
        pass
    return results


async def archive_has_code(code: Any, lookback: int = 200) -> bool:
    """
    Check recent MOD_ARCHIVE messages for a matching infraction code to avoid duplicates.
    """
    archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not archive_ch:
        return False
    try:
        async for m in archive_ch.history(limit=lookback):
            parsed = _extract_json_from_codeblock(m.content or "")
            if parsed and parsed.get("event_type") == "infract":
                if str(parsed.get("code")) == str(code):
                    return True
                # also check original infraction message id if present
                if parsed.get("infraction_message_id") and parsed.get("infraction_message_id") == code:
                    return True
    except Exception:
        pass
    return False


# ====== STAFF COMMANDS (including infraction group) =======
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
        # Preserve original behavior but also archive the infraction to MOD_ARCHIVE and moderation logs
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

        infra_channel = interaction.guild.get_channel(INFRACTION_CHANNEL_ID)
        sent_inf_msg = None
        if infra_channel:
            try:
                # keep ping behavior as before
                sent_inf_msg = await infra_channel.send(content=user.mention, embed=embed)
            except discord.Forbidden:
                pass
            except Exception:
                pass

        # Prepare details for archive and mod-log
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        details = {
            "event_type": "infract",
            "code": code,
            "user": f"{user} ({getattr(user, 'id', None)})",
            "user_id": getattr(user, "id", None),
            "punishment": punishment,
            "reason": reason,
            "issued_by": f"{interaction.user} ({interaction.user.id})",
            "expires": expires,
            "timestamp": now_str,
            "infraction_message_id": getattr(sent_inf_msg, "id", None),
            "attachments": [],
            "extra": None,
        }

        # Send a moderation-log entry (with Expand button) to LOGGING_CHANNEL_ID and archive in MOD_ARCHIVE
        log_ch = await ensure_channel(LOGGING_CHANNEL_ID)
        if log_ch:
            log_embed = discord.Embed(title="Staff Infraction Issued", color=discord.Color.red())
            log_embed.add_field(name="User", value=f"{user}", inline=True)
            log_embed.add_field(name="Code", value=str(code), inline=True)
            log_embed.add_field(name="Punishment", value=punishment, inline=True)
            log_embed.add_field(name="Issued By", value=f"{interaction.user}", inline=True)
            log_embed.set_footer(text=f"At {now_str}")
            try:
                await send_embed_with_expand(log_ch, log_embed, details)
            except Exception:
                pass

        # Also attempt to DM the user as before
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass
        except Exception:
            pass

        await interaction.response.send_message(f"Infraction issued and {user.display_name} has been notified.", ephemeral=True)

    # other staff commands retained unchanged...
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

    # Infraction subcommands (group) implemented as two separate commands with shared prefix
    @app_commands.command(name="infraction_lookup", description="Lookup archived staff infractions (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(user="Filter by staff member", code="Filter by infraction code", limit="How many archive messages to search (max 1000)")
    async def infraction_lookup(self, interaction: discord.Interaction, user: Optional[discord.Member] = None, code: Optional[str] = None, limit: int = 200):
        """
        Lookup infractions in the mod-archive channel.
        """
        await interaction.response.defer(ephemeral=True)
        if limit <= 0:
            limit = 200
        if limit > 1000:
            limit = 1000

        found: List[Dict[str, Any]] = []
        archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
        if not archive_ch:
            await interaction.followup.send("Mod archive channel is not available.", ephemeral=True)
            return

        # iterate archive messages, parse JSON, match event_type 'infract'
        try:
            async for m in archive_ch.history(limit=limit):
                parsed = _extract_json_from_codeblock(m.content or "")
                if not parsed:
                    continue
                if parsed.get("event_type") != "infract":
                    continue
                # match by user id or code if provided
                if user:
                    uid = getattr(user, "id", None)
                    if parsed.get("user_id") and int(parsed.get("user_id")) != uid:
                        continue
                if code:
                    if str(parsed.get("code")) != str(code):
                        continue
                parsed["_archive_message_id"] = m.id
                found.append(parsed)
                if len(found) >= 50:
                    break
        except Exception:
            pass

        if not found:
            await interaction.followup.send("No matching infractions found in mod archive.", ephemeral=True)
            return

        # build a compact embed listing results
        embed = discord.Embed(title="Infraction Lookup Results", color=discord.Color.orange())
        lines = []
        for idx, item in enumerate(found[:20], start=1):
            ts = item.get("timestamp", "")
            code_str = str(item.get("code", "N/A"))
            user_str = item.get("user", "Unknown")
            punishment = item.get("punishment", "N/A")
            issuer = item.get("issued_by", "Unknown")
            archive_id = item.get("_archive_message_id")
            line = f"{idx}) [{ts}] Code: `{code_str}` • User: {user_str} • Punishment: {punishment} • Issued by: {issuer} • ArchiveID: `{archive_id}`"
            lines.append(line)
        embed.description = "\n".join(lines[:25])
        embed.set_footer(text=f"Showing {len(found[:20])} of {len(found)} matches. Use the ArchiveID with Expand buttons in logs/mod-archive.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="infraction_scan", description="Scan the old infractions channel and archive missing entries (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(limit="How many messages to scan from the infraction channel (max 2000)")
    async def infraction_scan(self, interaction: discord.Interaction, limit: int = 1000):
        """
        Scan INFRACTION_CHANNEL_ID history and archive any infractions not present in the mod-archive.
        """
        await interaction.response.defer(ephemeral=True)
        if limit <= 0:
            limit = 1000
        if limit > 2000:
            limit = 2000

        infra_ch = await ensure_channel(INFRACTION_CHANNEL_ID)
        if not infra_ch:
            await interaction.followup.send("Infraction channel not available.", ephemeral=True)
            return

        archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
        if not archive_ch:
            await interaction.followup.send("Mod archive channel not available. Create it and ensure bot can post/read.", ephemeral=True)
            return

        scanned = 0
        archived = 0
        skipped = 0
        errors = 0

        try:
            async for msg in infra_ch.history(limit=limit):
                scanned += 1
                # try to parse embeds first
                parsed_infraction = None

                # check embeds for the familiar infraction embed structure
                if msg.embeds:
                    for e in msg.embeds:
                        title = getattr(e, "title", "") or ""
                        if "infraction" in title.lower():
                            # try to extract code from title (e.g., "⚠️ Staff Infraction - Code 1234")
                            code_match = re.search(r"code\s*([0-9]{3,6})", title, flags=re.IGNORECASE)
                            code_val = code_match.group(1) if code_match else None
                            fields = {}
                            try:
                                for f in getattr(e, "fields", []):
                                    fields[f.name.lower()] = f.value
                            except Exception:
                                pass
                            parsed_infraction = {
                                "code": code_val,
                                "user": fields.get("user") or fields.get("user", ""),
                                "punishment": fields.get("punishment", ""),
                                "reason": fields.get("reason", ""),
                                "issued_by": fields.get("issued by", "") or fields.get("issued_by", ""),
                                "expires": fields.get("expires", "") or "",
                                "timestamp": getattr(msg, "created_at", "").strftime("%Y-%m-%d %H:%M:%S UTC") if getattr(msg, "created_at", None) else "",
                                "infraction_message_id": msg.id,
                                "event_type": "infract",
                                "attachments": [a.url for a in msg.attachments] if msg.attachments else [],
                                "extra": None,
                            }
                            break

                # fallback: try to detect code in plain message content
                if not parsed_infraction:
                    content = (msg.content or "")
                    if "infraction" in content.lower() or "staff infraction" in content.lower():
                        code_match = re.search(r"code\s*([0-9]{3,6})", content, flags=re.IGNORECASE)
                        code_val = code_match.group(1) if code_match else None
                        # best-effort: find mentions / lines for Punishment / Reason / Issued By
                        punishment = ""
                        reason = ""
                        issued_by = ""
                        # simple heuristics: lines starting with "Punishment:", "Reason:", "Issued By:"
                        for line in content.splitlines():
                            l = line.strip()
                            if l.lower().startswith("punishment"):
                                _, _, val = l.partition(":")
                                punishment = val.strip()
                            if l.lower().startswith("reason"):
                                _, _, val = l.partition(":")
                                reason = val.strip()
                            if l.lower().startswith("issued by"):
                                _, _, val = l.partition(":")
                                issued_by = val.strip()
                        parsed_infraction = {
                            "code": code_val,
                            "user": None,
                            "punishment": punishment,
                            "reason": reason,
                            "issued_by": issued_by,
                            "expires": "",
                            "timestamp": getattr(msg, "created_at", "").strftime("%Y-%m-%d %H:%M:%S UTC") if getattr(msg, "created_at", None) else "",
                            "infraction_message_id": msg.id,
                            "event_type": "infract",
                            "attachments": [a.url for a in msg.attachments] if msg.attachments else [],
                            "extra": {"raw_content": content[:2000]},
                        }

                if not parsed_infraction:
                    skipped += 1
                    continue

                # check for duplicates in archive by code or infraction_message_id
                duplicate = False
                try:
                    # first try code match
                    code_to_check = parsed_infraction.get("code")
                    if code_to_check and await archive_has_code(code_to_check, lookback=500):
                        duplicate = True
                    else:
                        # check by infraction message id
                        async for am in archive_ch.history(limit=500):
                            p = _extract_json_from_codeblock(am.content or "")
                            if not p:
                                continue
                            # compare infraction_message_id if present
                            if p.get("infraction_message_id") and p.get("infraction_message_id") == parsed_infraction.get("infraction_message_id"):
                                duplicate = True
                                break
                except Exception:
                    # on any error, be conservative and skip to avoid duplicates
                    duplicate = True

                if duplicate:
                    skipped += 1
                    continue

                # create details and archive
                details = {
                    "event_type": "infract",
                    "code": parsed_infraction.get("code"),
                    "user": parsed_infraction.get("user"),
                    "user_id": None,
                    "punishment": parsed_infraction.get("punishment"),
                    "reason": parsed_infraction.get("reason"),
                    "issued_by": parsed_infraction.get("issued_by"),
                    "expires": parsed_infraction.get("expires"),
                    "timestamp": parsed_infraction.get("timestamp"),
                    "infraction_message_id": parsed_infraction.get("infraction_message_id"),
                    "attachments": parsed_infraction.get("attachments", []),
                    "extra": parsed_infraction.get("extra", None),
                }

                try:
                    # archive into MOD_ARCHIVE and post a log with Expand button into LOGGING_CHANNEL_ID
                    log_ch = await ensure_channel(LOGGING_CHANNEL_ID)
                    if log_ch:
                        log_embed = discord.Embed(title="(Imported) Staff Infraction", color=discord.Color.red())
                        log_embed.add_field(name="Code", value=str(details.get("code") or "N/A"), inline=True)
                        log_embed.add_field(name="Punishment", value=details.get("punishment") or "N/A", inline=True)
                        log_embed.add_field(name="Issued By", value=details.get("issued_by") or "Unknown", inline=True)
                        log_embed.set_footer(text=f"At {details.get('timestamp')}")
                        await send_embed_with_expand(log_ch, log_embed, details)
                    archived += 1
                    # be courteous to rate limits
                    await asyncio.sleep(0.12)
                except Exception:
                    errors += 1
                    await asyncio.sleep(0.25)
                    continue

        except Exception:
            await interaction.followup.send("Scanning failed due to an unexpected error.", ephemeral=True)
            return

        summary = f"Scan complete. Scanned: {scanned}, Archived: {archived}, Skipped (duplicates/irrelevant): {skipped}, Errors: {errors}"
        await interaction.followup.send(summary, ephemeral=True)


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

        # Command logging for message-based commands and '-' triggers (embed + Expand button backed by Discord storage)
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
                    # send embed with Expand button and store details into mod-archive
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


# ====== SERVER WARNINGS (reworked to use Expand + archive) =======
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
        # If component interaction (button press)
        if interaction.type == discord.InteractionType.component:
            # Safe-get custom_id
            cid = None
            try:
                if isinstance(interaction.data, dict):
                    cid = interaction.data.get("custom_id") or interaction.data.get("customID") or interaction.data.get("component_type")
            except Exception:
                cid = None

            if cid and isinstance(cid, str) and cid.startswith("expand:"):
                # parse archive id
                try:
                    archive_id_str = cid.split(":", 1)[1]
                    archive_id = int(archive_id_str)
                except Exception:
                    archive_id = None

                if not archive_id:
                    try:
                        await interaction.response.send_message("Details are not available.", ephemeral=True)
                    except Exception:
                        pass
                    return

                # fetch archive message from mod-archive channel
                try:
                    archive_ch = bot.get_channel(MOD_ARCHIVE_CHANNEL_ID)
                    if not archive_ch:
                        archive_ch = await bot.fetch_channel(MOD_ARCHIVE_CHANNEL_ID)
                except Exception:
                    archive_ch = None

                if not archive_ch:
                    try:
                        await interaction.response.send_message("Details are not available (archive channel missing).", ephemeral=True)
                    except Exception:
                        pass
                    return

                try:
                    archive_msg = await archive_ch.fetch_message(archive_id)
                except Exception:
                    archive_msg = None

                if not archive_msg:
                    try:
                        await interaction.response.send_message("Detailed information not available (message missing).", ephemeral=True)
                    except Exception:
                        pass
                    return

                # Parse JSON from archive message content if present
                details = None
                try:
                    content = archive_msg.content or ""
                    # strip triple backticks if present
                    parsed = _extract_json_from_codeblock(content)
                    details = parsed
                except Exception:
                    details = None

                # If parsing failed and embed exists, try to extract from embed fields
                if details is None and archive_msg.embeds:
                    try:
                        e = archive_msg.embeds[0]
                        details = {}
                        for f in getattr(e, "fields", []):
                            details[f.name] = f.value
                        if getattr(e, "footer", None) and getattr(e.footer, "text", None):
                            details["timestamp"] = e.footer.text
                    except Exception:
                        details = None

                # Fallback: show raw content
                if details is None:
                    try:
                        raw_text = archive_msg.content or "No further details available."
                        if len(raw_text) > 1900:
                            raw_text = raw_text[:1900] + "..."
                        resp_embed = discord.Embed(title="Detailed Log Information", description=raw_text, color=discord.Color.dark_blue())
                        await interaction.response.send_message(embed=resp_embed, ephemeral=True)
                    except Exception:
                        try:
                            await interaction.response.send_message("Failed to retrieve details.", ephemeral=True)
                        except Exception:
                            pass
                    return

                # Build an embed with as many fields as possible from details dict
                try:
                    detail_embed = discord.Embed(title="Detailed Log Information", color=discord.Color.dark_blue())
                    ts = details.get("timestamp")
                    if ts:
                        detail_embed.set_footer(text=f"Logged at {ts}")

                    # iterate through known keys in a helpful order
                    keys_order = ["event_type", "user", "user_id", "command", "code", "content", "punishment", "issued_by", "expires", "channel", "channel_id", "guild", "guild_id", "message_id", "infraction_message_id", "attachments", "extra"]
                    for key in keys_order:
                        if key in details and details.get(key) not in (None, "", []):
                            value = details.get(key)
                            if isinstance(value, (dict, list)):
                                value = json.dumps(value, default=str, ensure_ascii=False)
                            text = str(value)
                            if len(text) > 1024:
                                text = text[:1020] + "..."
                            detail_embed.add_field(name=key.replace("_", " ").title(), value=text, inline=False)

                    # Add any remaining keys
                    for k, v in details.items():
                        if k in keys_order:
                            continue
                        if v in (None, "", []):
                            continue
                        text = json.dumps(v, default=str, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
                        if len(text) > 1024:
                            text = text[:1020] + "..."
                        detail_embed.add_field(name=str(k), value=text, inline=False)

                    await interaction.response.send_message(embed=detail_embed, ephemeral=True)
                except Exception:
                    try:
                        await interaction.response.send_message("Failed to build details embed.", ephemeral=True)
                    except Exception:
                        pass

                return  # handled the component interaction

        # If not a component interaction, handle application command logging as before
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
            bot.add_cog(StaffCommands(bot))
        except Exception:
            pass
    if not bot.get_cog("PublicCommands"):
        try:
            bot.add_cog(PublicCommands(bot))
        except Exception:
            pass
    if not bot.get_cog("AutoResponder"):
        try:
            bot.add_cog(AutoResponder(bot))
        except Exception:
            pass

    guild_obj = discord.Object(id=MAIN_GUILD_ID)
    try:
        bot.tree.copy_global_to(guild=guild_obj)
        # sync without awaiting blocking if running in some environments; keep await as previous pattern
        asyncio.create_task(bot.tree.sync(guild=guild_obj))
        logger.info("Slash commands sync scheduled.")
    except Exception:
        logger.exception("Failed to schedule slash command sync")


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
