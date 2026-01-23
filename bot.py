# discord_bot.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import asyncio
from datetime import datetime, timezone, timedelta
import random
import logging
from typing import Any, Dict, Optional, List
import json
import re
import inspect

# ====== CONFIG =======
# Get token from environment or hardcode for testing
TOKEN = os.environ.get("DISCORD_TOKEN")
# For testing, you can temporarily hardcode: TOKEN = "your_token_here"
if not TOKEN:
    print("ERROR: DISCORD_TOKEN environment variable is not set")
    print("Please set it or temporarily hardcode it in the file")
    # Uncomment the line below and add your token for testing
    # TOKEN = "your_bot_token_here"
    # raise RuntimeError("DISCORD_TOKEN environment variable is not set")

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

# Internal Affairs related IDs
IA_ROLE_ID = 1404679512276602881
IA_AGENT_ROLE_ID = 1400189498087964734
IA_SUPERVISOR_ROLE_ID = 1400189341590093967

# IA category where case channels are created
IA_CATEGORY_ID = 1452383883336351794

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


# ------------------------
# Permission predicate helpers (added/fixed)
# ------------------------
def _has_any_role(member: Optional[discord.Member], role_ids: List[int]) -> bool:
    if not member:
        return False
    try:
        return any(r.id in role_ids for r in getattr(member, "roles", []))
    except Exception:
        logger.exception("Error checking roles for member")
        return False


def is_bod(interaction: discord.Interaction) -> bool:
    try:
        member = None
        if isinstance(interaction.user, discord.Member):
            member = interaction.user
        elif interaction.guild:
            member = interaction.guild.get_member(interaction.user.id)
        if member and _has_any_role(member, STAFF_ROLES):
            return True
    except Exception:
        logger.exception("is_bod check failed")
    raise app_commands.CheckFailure("You do not have permission to use this command.")


def is_ia(interaction: discord.Interaction) -> bool:
    try:
        member = None
        if isinstance(interaction.user, discord.Member):
            member = interaction.user
        elif interaction.guild:
            member = interaction.guild.get_member(interaction.user.id)
        if member and _has_any_role(member, [IA_ROLE_ID, IA_AGENT_ROLE_ID, IA_SUPERVISOR_ROLE_ID]):
            return True
    except Exception:
        logger.exception("is_ia check failed")
    raise app_commands.CheckFailure("You do not have permission to use this command.")


# ------------------------
# Anti-ping in-memory map + helpers (added)
# ------------------------
# anti_ping_map: user_id -> {
#   "_archive_message_id": int,
#   "status": "active"|"paused"|"stopped",
#   "started_at": ISO str,
#   "duration_hours": Optional[float],
#   "expires_at": Optional[ISO str]  # computed if duration set
# }
anti_ping_map: Dict[int, Dict[str, Any]] = {}
ANTIPING_ARCHIVE_TYPE = "antiping"


def _antiping_is_expired(entry: Dict[str, Any]) -> bool:
    exp = entry.get("expires_at")
    if not exp:
        return False
    try:
        exp_dt = datetime.fromisoformat(exp)
        # make timezone-aware UTC if naive
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        else:
            exp_dt = exp_dt.astimezone(timezone.utc)
        return datetime.now(timezone.utc) >= exp_dt
    except Exception:
        logger.exception("Failed to parse expires_at for antiping entry")
        return False


async def _load_antiping_from_archive():
    """Populate anti_ping_map from MOD_ARCHIVE on startup."""
    arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not arch_ch:
        logger.info("Mod archive channel not available for antiping load")
        return
    try:
        async for m in arch_ch.history(limit=5000):
            parsed = _extract_json_from_codeblock(m.content or "")
            if not parsed:
                continue
            if parsed.get("event_type") != ANTIPING_ARCHIVE_TYPE:
                continue
            uid = parsed.get("user_id")
            if not uid:
                continue
            try:
                uid_int = int(uid)
            except Exception:
                continue
            status = parsed.get("status", "stopped")
            entry = {
                "_archive_message_id": m.id,
                "status": status,
                "started_at": parsed.get("started_at"),
                "duration_hours": parsed.get("duration_hours"),
                "expires_at": parsed.get("expires_at"),
            }
            if status == "active" and not _antiping_is_expired(entry):
                anti_ping_map[uid_int] = entry
    except Exception:
        logger.exception("Failed to load anti-ping archive entries")


async def _save_antiping_entry(parsed: Dict[str, Any]) -> Optional[int]:
    """Save or update anti-ping entry in MOD_ARCHIVE."""
    arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not arch_ch:
        logger.info("Mod archive channel not available for saving antiping entry")
        return None
    try:
        content = json.dumps(parsed, default=str, ensure_ascii=False, indent=2)
    except Exception:
        content = json.dumps({k: str(v) for k, v in parsed.items()}, ensure_ascii=False, indent=2)
    payload = f"```json\n{content}\n```"
    try:
        aid = parsed.get("_archive_message_id") or parsed.get("_archive_msg_id")
        if aid:
            try:
                msg = await arch_ch.fetch_message(int(aid))
                await msg.edit(content=payload)
                return msg.id
            except Exception:
                logger.exception("Failed to edit existing archive message; will create new")
        newm = await arch_ch.send(content=payload)
        return newm.id
    except Exception:
        logger.exception("Failed to save antiping archive entry")
        return None


# ------------------------
# Helper utilities (from backup)
# ------------------------
async def ensure_channel(channel_id: int) -> Optional[discord.TextChannel]:
    ch = bot.get_channel(channel_id)
    if ch:
        return ch
    try:
        ch = await bot.fetch_channel(channel_id)
        return ch
    except Exception:
        logger.exception(f"Failed to fetch channel {channel_id}")
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
                logger.debug("Found braces but failed to parse JSON inside codeblock")
                return None
    return None


async def archive_details_to_mod_channel(details: Dict[str, Any]) -> Optional[int]:
    """
    Post a JSON-encoded details message to the MOD_ARCHIVE_CHANNEL_ID.
    Returns the archive message id or None.
    """
    archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not archive_ch:
        logger.info("Mod archive channel not available for posting details")
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
        logger.exception("Failed to send archive details to mod channel")
        return None


async def edit_archive_message(archive_msg_id: int, details: Dict[str, Any]) -> bool:
    """
    Edit an existing MOD_ARCHIVE message (archive_msg_id) to contain updated JSON details.
    Returns True on success.
    """
    archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not archive_ch:
        logger.info("Mod archive channel not available for editing message")
        return False
    try:
        archive_msg = await archive_ch.fetch_message(archive_msg_id)
    except Exception:
        logger.exception("Failed to fetch archive message for editing")
        return False
    try:
        content = json.dumps(details, default=str, ensure_ascii=False, indent=2)
    except Exception:
        content = json.dumps({k: str(v) for k, v in details.items()}, ensure_ascii=False, indent=2)
    try:
        await archive_msg.edit(content=f"```json\n{content}\n```")
        return True
    except Exception:
        logger.exception("Failed to edit archive message")
        return False


class ExpandView(discord.ui.View):
    def __init__(self, archive_message_id: int):
        super().__init__(timeout=None)
        # store archive message id in the view for convenience; button custom_id will also carry it
        self.archive_message_id = archive_message_id
        # Add a button whose custom_id encodes the archive message id
        custom_id = f"expand:{archive_message_id}"
        self.add_item(discord.ui.Button(label="Expand", style=discord.ButtonStyle.primary, custom_id=custom_id))


async def send_embed_with_expand(target_channel: discord.abc.GuildChannel | discord.TextChannel, embed: discord.Embed, details: Dict[str, Any]):
    """
    Sends an embed to the given target_channel.
    Only archive (store in MOD_ARCHIVE) and attach Expand button for event types: 'infract', 'promote', 'ia_case', 'antiping'.
    For other event types, just post the embed (no archive, no Expand button).
    """
    try:
        event_type = details.get("event_type") if isinstance(details, dict) else None
        # Only archive infractions, promotions and IA cases and antiping
        if event_type in ("infract", "promote", "ia_case", ANTIPING_ARCHIVE_TYPE):
            archive_msg_id = await archive_details_to_mod_channel(details)
            archive_id = archive_msg_id or 0
            view = ExpandView(archive_id)
            try:
                await target_channel.send(embed=embed, view=view)
            except Exception:
                logger.exception("Failed to send embed with view; sending without view")
                try:
                    await target_channel.send(embed=embed)
                except Exception:
                    logger.exception("Failed to send embed without view")
        else:
            # Do not archive; just send embed without view
            try:
                await target_channel.send(embed=embed)
            except Exception:
                logger.exception("Failed to send embed to target channel")
    except Exception:
        logger.exception("send_embed_with_expand encountered an error")


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
        logger.exception("Failed while scanning archived infractions")
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
        logger.exception("archive_has_code failed")
    return False


# Shared scanning helper (from backup; kept for manual /infraction scan)
async def scan_and_archive_infractions(limit: int = 500) -> Dict[str, int]:
    """
    Scan INFRACTION_CHANNEL_ID up to `limit` messages and archive missing infractions into MOD_ARCHIVE.
    Returns summary dict with counts.
    """
    infra_ch = await ensure_channel(INFRACTION_CHANNEL_ID)
    if not infra_ch:
        return {"scanned": 0, "archived": 0, "skipped": 0, "errors": 0, "available": False}
    archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not archive_ch:
        return {"scanned": 0, "archived": 0, "skipped": 0, "errors": 0, "available": False}

    scanned = archived = skipped = errors = 0
    try:
        async for msg in infra_ch.history(limit=limit):
            scanned += 1
            parsed_infraction = None

            if msg.embeds:
                for e in msg.embeds:
                    title = getattr(e, "title", "") or ""
                    if "infraction" in title.lower():
                        code_match = re.search(r"code\s*([0-9]{3,6})", title, flags=re.IGNORECASE)
                        code_val = code_match.group(1) if code_match else None
                        fields = {}
                        try:
                            for f in getattr(e, "fields", []):
                                fields[f.name.lower()] = f.value
                        except Exception:
                            logger.exception("Failed to parse embed fields for infraction")
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

            if not parsed_infraction:
                content = (msg.content or "")
                if "infraction" in content.lower() or "staff infraction" in content.lower():
                    code_match = re.search(r"code\s*([0-9]{3,6})", content, flags=re.IGNORECASE)
                    code_val = code_match.group(1) if code_match else None
                    punishment = reason = issued_by = ""
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

            duplicate = False
            try:
                code_to_check = parsed_infraction.get("code")
                if code_to_check and await archive_has_code(code_to_check, lookback=500):
                    duplicate = True
                else:
                    async for am in archive_ch.history(limit=500):
                        p = _extract_json_from_codeblock(am.content or "")
                        if not p:
                            continue
                        if p.get("infraction_message_id") and p.get("infraction_message_id") == parsed_infraction.get("infraction_message_id"):
                            duplicate = True
                            break
            except Exception:
                logger.exception("Error checking duplicates in archive")
                duplicate = True

            if duplicate:
                skipped += 1
                continue

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
                log_ch = await ensure_channel(LOGGING_CHANNEL_ID)
                if log_ch:
                    log_embed = discord.Embed(title="(Imported) Staff Infraction", color=discord.Color.red())
                    log_embed.add_field(name="Code", value=str(details.get("code") or "N/A"), inline=True)
                    log_embed.add_field(name="Punishment", value=details.get("punishment") or "N/A", inline=True)
                    log_embed.add_field(name="Issued By", value=details.get("issued_by") or "Unknown", inline=True)
                    log_embed.set_footer(text=f"At {details.get('timestamp')}")
                    await send_embed_with_expand(log_ch, log_embed, details)
                archived += 1
                await asyncio.sleep(0.12)
            except Exception:
                errors += 1
                logger.exception("Failed to archive imported infraction")
                await asyncio.sleep(0.25)
                continue
    except Exception:
        logger.exception("scan_and_archive_infractions failed during history iteration")
        return {"scanned": scanned, "archived": archived, "skipped": skipped, "errors": errors, "available": True}

    return {"scanned": scanned, "archived": archived, "skipped": skipped, "errors": errors, "available": True}


# ====== Slash command groups: Infraction & Promotion & IA (from backup) =======
class InfractionGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="infraction", description="Infraction commands (BOD only)")

    @app_commands.command(name="lookup", description="Lookup prior infractions for a staff member (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(staff="Staff member to lookup (the person who received infractions)")
    async def lookup(self, interaction: discord.Interaction, staff: discord.Member):
        await interaction.response.defer(ephemeral=False)
        archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
        if not archive_ch:
            await interaction.followup.send("Mod archive channel is not available.", ephemeral=True)
            return

        found: List[Dict[str, Any]] = []
        lookup_id = getattr(staff, "id", None)
        try:
            async for m in archive_ch.history(limit=2000):
                parsed = _extract_json_from_codeblock(m.content or "")
                if not parsed:
                    continue
                if parsed.get("event_type") != "infract":
                    continue
                uid = parsed.get("user_id")
                if uid:
                    try:
                        if int(uid) == int(lookup_id):
                            parsed["_archive_message_id"] = m.id
                            found.append(parsed)
                    except Exception:
                        if str(lookup_id) in str(parsed.get("user", "")):
                            parsed["_archive_message_id"] = m.id
                            found.append(parsed)
                else:
                    if str(lookup_id) in str(parsed.get("user", "")):
                        parsed["_archive_message_id"] = m.id
                        found.append(parsed)
        except Exception:
            logger.exception("Failed during infraction lookup history scan")

        if not found:
            await interaction.followup.send(f"No infractions found for {staff.display_name}.", ephemeral=False)
            return

        embed = discord.Embed(title="Infraction Lookup", color=discord.Color.orange())
        embed.set_thumbnail(url=staff.display_avatar.url if getattr(staff, "display_avatar", None) else None)
        embed.add_field(name="Staff Member", value=f"{staff} • {staff.id}", inline=False)
        embed.add_field(name="Total Infractions Found", value=str(len(found)), inline=False)

        shown = 0
        for item in found[:10]:
            shown += 1
            code = item.get("code", "N/A")
            punishment = item.get("punishment", "N/A")
            reason = item.get("reason", "N/A")
            issued_by = item.get("issued_by", "N/A")
            ts = item.get("timestamp", "N/A")
            archive_id = item.get("_archive_message_id", "N/A")
            value = (
                f"• Code: `{code}`\n"
                f"• Punishment: {punishment}\n"
                f"• Reason: {reason}\n"
                f"• Issued By: {issued_by}\n"
                f"• When: {ts}\n"
                f"• ArchiveID: `{archive_id}`"
            )
            embed.add_field(name=f"Infraction #{shown}", value=value, inline=False)

        if len(found) > 10:
            embed.set_footer(text=f"Showing 10 most recent of {len(found)} infractions. Use archive messages to Expand for full details.")
        else:
            embed.set_footer(text="Use Expand on archive messages for full details.")

        await interaction.followup.send(embed=embed, ephemeral=False)

    @app_commands.command(name="scan", description="Scan old infractions channel and archive missing entries (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(limit="How many messages to scan from the infraction channel (max 2000)")
    async def scan(self, interaction: discord.Interaction, limit: int = 1000):
        await interaction.response.defer(ephemeral=True)
        if limit <= 0:
            limit = 1000
        if limit > 2000:
            limit = 2000

        result = await scan_and_archive_infractions(limit=limit)
        if not result.get("available"):
            await interaction.followup.send("Infraction or archive channel not available.", ephemeral=True)
            return
        summary = f"Scan complete. Scanned: {result['scanned']}, Archived: {result['archived']}, Skipped: {result['skipped']}, Errors: {result['errors']}"
        await interaction.followup.send(summary, ephemeral=True)


class PromotionGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="promotion", description="Promotion commands (BOD only)")

    @app_commands.command(name="lookup", description="Lookup promotions for a staff member (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(staff="Staff member to lookup promotions for")
    async def lookup(self, interaction: discord.Interaction, staff: discord.Member):
        await interaction.response.defer(ephemeral=False)
        archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
        if not archive_ch:
            await interaction.followup.send("Mod archive channel is not available.", ephemeral=True)
            return

        found: List[Dict[str, Any]] = []
        lookup_id = getattr(staff, "id", None)
        try:
            async for m in archive_ch.history(limit=2000):
                parsed = _extract_json_from_codeblock(m.content or "")
                if not parsed:
                    continue
                if parsed.get("event_type") != "promote":
                    continue
                uid = parsed.get("user_id")
                if uid:
                    try:
                        if int(uid) == int(lookup_id):
                            parsed["_archive_message_id"] = m.id
                            found.append(parsed)
                    except Exception:
                        if str(lookup_id) in str(parsed.get("user", "")):
                            parsed["_archive_message_id"] = m.id
                            found.append(parsed)
                else:
                    if str(lookup_id) in str(parsed.get("user", "")):
                        parsed["_archive_message_id"] = m.id
                        found.append(parsed)
        except Exception:
            logger.exception("Failed during promotion lookup history scan")

        if not found:
            await interaction.followup.send(f"No promotions found for {staff.display_name}.", ephemeral=False)
            return

        embed = discord.Embed(title="Promotion Lookup", color=discord.Color.green())
        embed.set_thumbnail(url=staff.display_avatar.url if getattr(staff, "display_avatar", None) else None)
        embed.add_field(name="Staff Member", value=f"{staff} • {staff.id}", inline=False)
        embed.add_field(name="Total Promotions Found", value=str(len(found)), inline=False)

        shown = 0
        for item in found[:10]:
            shown += 1
            new_rank = item.get("new_rank", "N/A")
            reason = item.get("reason", "N/A")
            promoted_by = item.get("promoted_by", "N/A")
            ts = item.get("timestamp", "N/A")
            archive_id = item.get("_archive_message_id", "N/A")
            value = (
                f"• New Rank: {new_rank}\n"
                f"• Reason: {reason}\n"
                f"• Promoted By: {promoted_by}\n"
                f"• When: {ts}\n"
                f"• ArchiveID: `{archive_id}`"
            )
            embed.add_field(name=f"Promotion #{shown}", value=value, inline=False)

        if len(found) > 10:
            embed.set_footer(text=f"Showing 10 most recent of {len(found)} promotions. Use archive messages to Expand for full details.")
        else:
            embed.set_footer(text="Use Expand on archive messages for full details.")

        await interaction.followup.send(embed=embed, ephemeral=False)


class IAGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="ia", description="Internal Affairs commands (IA only)")

    @app_commands.command(name="open", description="Open an I.A. Case")
    @app_commands.check(is_ia)
    @app_commands.describe(
        investigated="Member being investigated (required)",
        reason="Reason for opening this case (required)",
        details="Additional description (optional)",
        include_agents="Include I.A. Agents (role)",
        include_supervisors="Include I.A. Supervisors (role)",
        include_bod="Include Board of Directors (role)",
        include_owners="Include server owner(s)"
    )
    async def open(
        self,
        interaction: discord.Interaction,
        investigated: discord.Member,
        reason: str,
        details: Optional[str] = None,
        include_agents: bool = False,
        include_supervisors: bool = False,
        include_bod: bool = False,
        include_owners: bool = False,
    ):
        await interaction.response.defer(ephemeral=False)

        # Compute next case number by scanning MOD_ARCHIVE for ia_case entries
        case_num = 1
        archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
        if archive_ch:
            try:
                async for m in archive_ch.history(limit=2000):
                    parsed = _extract_json_from_codeblock(m.content or "")
                    if parsed and parsed.get("event_type") == "ia_case":
                        try:
                            existing = int(parsed.get("case_number", 0))
                            if existing >= case_num:
                                case_num = existing + 1
                        except Exception:
                            continue
            except Exception:
                logger.exception("Failed scanning archive for existing IA cases")

        case_str = f"{case_num:06d}"  # six digits zero-padded

        # Create channel under IA_CATEGORY_ID
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Guild context unavailable.", ephemeral=True)
            return

        category = discord.utils.get(guild.categories, id=IA_CATEGORY_ID)
        # Build channel name
        channel_name = f"ia-case-{case_str}-open"

        # Prepare permission overwrites
        overwrites: Dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {}
        everyone_role = guild.default_role
        overwrites[everyone_role] = discord.PermissionOverwrite(view_channel=False)

        # Always allow IA role
        ia_role = guild.get_role(IA_ROLE_ID)
        if ia_role:
            overwrites[ia_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        allowed_role_ids = []
        allowed_member_ids = []

        # Add selected roles
        if include_agents:
            r = guild.get_role(IA_AGENT_ROLE_ID)
            if r:
                overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                allowed_role_ids.append(r.id)
        if include_supervisors:
            r = guild.get_role(IA_SUPERVISOR_ROLE_ID)
            if r:
                overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                allowed_role_ids.append(r.id)
        if include_bod:
            for rid in STAFF_ROLES:
                r = guild.get_role(rid)
                if r:
                    overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                    allowed_role_ids.append(r.id)
        if include_owners:
            owner = guild.get_member(OWNER_ID)
            if owner:
                overwrites[owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                allowed_member_ids.append(owner.id)

        # Ensure investigated member cannot see the channel unless explicitly allowed (sensitive)
        # By default, do not grant the investigated member view permissions.
        # If you want to allow them, add logic here.
        # Create the channel
        try:
            new_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"IA case {case_str} opened by {interaction.user}"
            )
        except Exception:
            logger.exception("Failed to create IA case channel")
            await interaction.followup.send("Failed to create IA case channel. Check bot permissions.", ephemeral=True)
            return

        # Build initial embed
        embed = discord.Embed(title=f"IA Case {case_str}", color=discord.Color.dark_blue())
        embed.add_field(name="Investigated", value=f"{investigated} • {investigated.id}", inline=False)
        embed.add_field(name="Opened By", value=f"{interaction.user} • {interaction.user.id}", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        if details:
            embed.add_field(name="Details", value=details, inline=False)
        embed.set_footer(text=f"Case {case_str} • Opened at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

        # Archive the case details
        details_payload = {
            "event_type": "ia_case",
            "case_number": case_num,
            "case_string": case_str,
            "investigated": str(investigated),
            "investigated_id": investigated.id,
            "opened_by": str(interaction.user),
            "opened_by_id": interaction.user.id,
            "reason": reason,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "channel_id": new_channel.id,
            "allowed_role_ids": allowed_role_ids,
            "allowed_member_ids": allowed_member_ids,
        }
        try:
            archive_msg_id = await archive_details_to_mod_channel(details_payload)
            if archive_msg_id:
                details_payload["_archive_message_id"] = archive_msg_id
        except Exception:
            logger.exception("Failed to archive IA case details")

        # Send initial message in the new channel
        try:
            await new_channel.send(embed=embed)
        except Exception:
            logger.exception("Failed to send initial embed to IA channel")

        # Notify logging channel with expand button and archive
        try:
            log_ch = await ensure_channel(LOGGING_CHANNEL_ID)
            if log_ch:
                await send_embed_with_expand(log_ch, embed, details_payload)
        except Exception:
            logger.exception("Failed to notify logging channel about IA case")

        await interaction.followup.send(f"IA case {case_str} opened: {new_channel.mention}", ephemeral=False)


# Register groups as top-level commands (they will be added in on_ready)
# (We keep the classes defined above; registration happens in on_ready)


# ------------------------
# on_ready and startup tasks
# ------------------------
@bot.event
async def on_ready():
    try:
        logger.info(f"Bot ready: {bot.user} (ID: {bot.user.id})")
    except Exception:
        logger.exception("Error logging bot ready info")

    # Register app command groups (only once)
    try:
        # Check if groups are already registered to avoid conflicts
        existing_commands = [cmd.name for cmd in bot.tree.get_commands()]
        
        groups_to_add = []
        if "infraction" not in existing_commands:
            groups_to_add.append(InfractionGroup())
        if "promotion" not in existing_commands:
            groups_to_add.append(PromotionGroup())
        if "ia" not in existing_commands:
            groups_to_add.append(IAGroup())
        
        for grp in groups_to_add:
            try:
                bot.tree.add_command(grp)
                logger.info(f"Added command group: {grp.name}")
            except Exception as e:
                logger.error(f"Failed to add group {grp.name}: {e}")
        
        # Sync to guild for faster registration during development
        try:
            # Use guild sync for immediate testing (faster than global sync)
            guild = discord.Object(id=MAIN_GUILD_ID)
            await bot.tree.sync(guild=guild)
            logger.info(f"App commands synced to guild {MAIN_GUILD_ID}")
            
            # Also try global sync as backup
            try:
                await bot.tree.sync()
                logger.info("App commands synced globally")
            except Exception as e:
                logger.warning(f"Global sync failed: {e}")
                
        except Exception as e:
            logger.error(f"Failed to sync app commands: {e}")
            logger.exception("Full sync error details:")
    except Exception:
        logger.exception("Failed to register app command groups")

    # Load anti-ping map from archive
    try:
        await _load_antiping_from_archive()
        logger.info(f"Loaded {len(anti_ping_map)} active anti-ping entries")
    except Exception:
        logger.exception("Failed to load anti-ping entries on startup")


# ------------------------
# Basic error handlers for app command checks
# ------------------------
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # Provide detailed feedback for debugging
    error_msg = str(error)
    logger.error(f"App command error: {error_msg}")
    logger.exception(f"Full error details: {error}")
    
    if isinstance(error, app_commands.CheckFailure):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to send check failure message: {e}")
    elif isinstance(error, app_commands.CommandInvokeError):
        try:
            if interaction.response.is_done():
                await interaction.followup.send("Command execution failed. Check bot logs.", ephemeral=True)
            else:
                await interaction.response.send_message("Command execution failed. Check bot logs.", ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to send invoke error message: {e}")
    else:
        logger.error(f"Unhandled app command error type: {type(error)}")
        try:
            if interaction.response.is_done():
                await interaction.followup.send("An unexpected error occurred.", ephemeral=True)
            else:
                await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to send generic error message: {e}")


# ------------------------
# Debug commands for testing
# ------------------------
@bot.command(name="ping")
async def ping_cmd(ctx: commands.Context):
    await ctx.send(f"Pong! Bot is online. Latency: {round(bot.latency * 1000)}ms")

@bot.command(name="sync")
@commands.has_permissions(administrator=True)
async def sync_commands(ctx: commands.Context):
    """Manually sync commands - for debugging"""
    try:
        await bot.tree.sync()
        await ctx.send("Commands synced globally!")
    except Exception as e:
        await ctx.send(f"Sync failed: {e}")

@bot.command(name="guildsync")
@commands.has_permissions(administrator=True)
async def guild_sync_commands(ctx: commands.Context):
    """Sync commands to current guild - for debugging"""
    try:
        await bot.tree.sync(guild=ctx.guild)
        await ctx.send(f"Commands synced to guild {ctx.guild.name}!")
    except Exception as e:
        await ctx.send(f"Guild sync failed: {e}")

@bot.command(name="debug")
@commands.has_permissions(administrator=True)
async def debug_info(ctx: commands.Context):
    """Show debug information"""
    commands_list = [cmd.name for cmd in bot.tree.get_commands()]
    embed = discord.Embed(title="Bot Debug Info", color=discord.Color.blue())
    embed.add_field(name="Registered Commands", value="\n".join(commands_list) or "None", inline=False)
    embed.add_field(name="Bot Latency", value=f"{round(bot.latency * 1000)}ms", inline=True)
    embed.add_field(name="Guild Count", value=str(len(bot.guilds)), inline=True)
    await ctx.send(embed=embed)


# ------------------------
# Run the bot
# ------------------------
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception:
        logger.exception("Bot crashed on run")
