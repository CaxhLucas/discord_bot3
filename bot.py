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
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is not set")

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
# Anti-ping in-memory map + helpers (added)
# ------------------------
# anti_ping_map: user_id -> {
#   "archive_msg_id": int,
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
        return datetime.now(timezone.utc) >= exp_dt
    except Exception:
        return False


async def _load_antiping_from_archive():
    """Populate anti_ping_map from MOD_ARCHIVE on startup."""
    arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not arch_ch:
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
                "archive_msg_id": m.id,
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
        return None
    try:
        content = json.dumps(parsed, default=str, ensure_ascii=False, indent=2)
    except Exception:
        content = json.dumps({k: str(v) for k, v in parsed.items()}, ensure_ascii=False, indent=2)
    payload = f"```json\n{content}\n```"
    try:
        aid = parsed.get("_archive_msg_id")
        if aid:
            try:
                msg = await arch_ch.fetch_message(int(aid))
                await msg.edit(content=payload)
                return msg.id
            except Exception:
                pass
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


async def edit_archive_message(archive_msg_id: int, details: Dict[str, Any]) -> bool:
    """
    Edit an existing MOD_ARCHIVE message (archive_msg_id) to contain updated JSON details.
    Returns True on success.
    """
    archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not archive_ch:
        return False
    try:
        archive_msg = await archive_ch.fetch_message(archive_msg_id)
    except Exception:
        return False
    try:
        content = json.dumps(details, default=str, ensure_ascii=False, indent=2)
    except Exception:
        content = json.dumps({k: str(v) for k, v in details.items()}, ensure_ascii=False, indent=2)
    try:
        await archive_msg.edit(content=f"```json\n{content}\n```")
        return True
    except Exception:
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
    Only archive (store in MOD_ARCHIVE) and attach Expand button for event types: 'infract', 'promote', 'ia_case'.
    For other event types, just post the embed (no archive, no Expand button).
    """
    try:
        event_type = details.get("event_type") if isinstance(details, dict) else None
        # Only archive infractions, promotions and IA cases
        if event_type in ("infract", "promote", "ia_case", ANTIPING_ARCHIVE_TYPE):
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
        else:
            # Do not archive; just send embed without view
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
                await asyncio.sleep(0.25)
                continue
    except Exception:
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
            pass

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
            pass

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
                pass

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
            r = guild.get_role(BOD_ROLE_ID)
            if r:
                overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                allowed_role_ids.append(r.id)

        # Include server owner(s)
        if include_owners:
            try:
                owner = await guild.fetch_member(guild.owner_id)
                overwrites[owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                allowed_member_ids.append(owner.id)
            except Exception:
                pass

        # Allow the investigated user to view and send (as requested)
        try:
            overwrites[investigated] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            allowed_member_ids.append(investigated.id)
        except Exception:
            pass

        # Allow the opener (interaction.user)
        try:
            opener_member = interaction.user
            overwrites[opener_member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            allowed_member_ids.append(opener_member.id)
        except Exception:
            pass

        # Ensure bot can see/send
        me = guild.me or guild.get_member(bot.user.id)
        if me:
            overwrites[me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True, read_message_history=True, manage_channels=True)

        # Create channel
        try:
            chan = await guild.create_text_channel(channel_name, category=category, overwrites=overwrites, reason=f"IA case opened by {interaction.user}")
        except Exception as e:
            await interaction.followup.send(f"Failed to create case channel: {e}", ephemeral=True)
            return

        # Prepare case embed (exact structure you requested, grammar lightly cleaned)
        case_embed = discord.Embed(title=f"Case {case_str}", color=discord.Color.red())
        case_embed.add_field(name="Investigating", value=f"{investigated.mention}", inline=False)
        case_embed.add_field(name="For", value=reason, inline=False)
        case_embed.add_field(name="Investigator", value=f"{interaction.user.mention}", inline=False)

        note_text = (
            "Note: DO NOT DM ANYONE about this case. Any information about this case must be put here or in evidence "
            f"<#{1404677593856348301}>. If you are the one being investigated, or you have any involvement; DO NOT LEAVE "
            "THE SERVER. If you do and rejoin, you WILL be staff-blacklisted <@&1371272556832882693>. After the case is closed "
            "DO NOT delete this channel so we have a record of this case."
        )
        case_embed.add_field(name="Important", value=note_text, inline=False)
        case_embed.add_field(name="Close", value='To close this case, please type `-close`', inline=False)

        # Send initial embed to the new channel and pin it
        try:
            sent = await chan.send(content=f"<@&{IA_ROLE_ID}> {investigated.mention}", embed=case_embed)
            try:
                await sent.pin(reason="Pin IA case initial embed")
            except Exception:
                pass
        except Exception:
            # even if send fails, continue
            sent = None

        # Archive the case to MOD_ARCHIVE
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        archive_details = {
            "event_type": "ia_case",
            "case_number": int(case_num),
            "case_string": case_str,
            "channel_id": chan.id,
            "guild_id": guild.id,
            "investigated_id": investigated.id,
            "investigated": f"{investigated} ({investigated.id})",
            "reason": reason,
            "description": details or "",
            "opened_by": f"{interaction.user} ({interaction.user.id})",
            "opened_by_id": interaction.user.id,
            "allowed_role_ids": allowed_role_ids,
            "allowed_member_ids": allowed_member_ids,
            "claimers": [],  # list of user ids
            "status": "open",
            "created_at": created_at,
            "closed_at": None,
            "closed_by": None,
        }
        archive_msg_id = None
        if await ensure_channel(MOD_ARCHIVE_CHANNEL_ID):
            archive_msg_id = await archive_details_to_mod_channel(archive_details)
        # Save archive reference in channel topic for quick lookup
        try:
            topic = f"ia_archive:{archive_msg_id or 0} case:{case_str}"
            await chan.edit(topic=topic)
        except Exception:
            pass

        await interaction.followup.send(f"Opened IA case {case_str} in {chan.mention}", ephemeral=False)


# ====== STAFF COMMANDS (existing ones kept from backup) =======
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
        promotion_message = None
        if channel:
            try:
                promotion_message = await channel.send(content=user.mention, embed=embed)
            except Exception:
                pass

        # Archive promotion details to mod-archive and send log with Expand button
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        details = {
            "event_type": "promote",
            "user": f"{user} ({getattr(user, 'id', None)})",
            "user_id": getattr(user, "id", None),
            "new_rank": new_rank,
            "reason": reason,
            "promoted_by": f"{interaction.user} ({interaction.user.id})",
            "timestamp": now_str,
            "promotion_message_id": getattr(promotion_message, "id", None),
            "extra": None,
        }
        log_ch = await ensure_channel(LOGGING_CHANNEL_ID)
        if log_ch:
            log_embed = discord.Embed(title="Staff Promotion Logged", color=discord.Color.green())
            log_embed.add_field(name="User", value=f"{user}", inline=True)
            log_embed.add_field(name="New Rank", value=new_rank, inline=True)
            log_embed.add_field(name="Promoted By", value=f"{interaction.user}", inline=True)
            log_embed.set_footer(text=f"At {now_str}")
            try:
                await send_embed_with_expand(log_ch, log_embed, details)
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


# ====== PUBLIC COMMANDS (merged: include antiping + suggest/partnerinfo) =======
class PublicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Anti-ping slash command (added)
    @app_commands.command(name="antiping", description="Click here to manage or turn on anti ping")
    async def antiping(self, interaction: discord.Interaction):
        try:
            modal = AntiPingModal(requester=interaction.user)
            await interaction.response.send_modal(modal)
        except Exception:
            try:
                await interaction.response.send_message("Failed to open Anti-Ping setup.", ephemeral=True)
            except Exception:
                pass

    # Original public commands
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


# ------------------------
# Modals (AntiPing + CloseReason)
# ------------------------
class AntiPingModal(discord.ui.Modal, title="Anti-Ping — Duration (optional)"):
    duration = discord.ui.TextInput(label="Duration in hours (leave blank for indefinite)", required=False, max_length=20, placeholder="e.g. 6 or 24")

    def __init__(self, requester: discord.Member):
        super().__init__()
        self.requester = requester

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        requester = self.requester
        requester_id = getattr(requester, "id", None)
        dur_text = self.duration.value.strip() if self.duration.value else ""
        duration_hours = None
        expires_at = None
        started_at = datetime.now(timezone.utc)
        if dur_text:
            try:
                duration_hours = float(dur_text)
                expires_dt = started_at + timedelta(hours=duration_hours)
                expires_at = expires_dt.isoformat()
            except Exception:
                duration_hours = None
                expires_at = None

        archive_entry = {
            "event_type": ANTIPING_ARCHIVE_TYPE,
            "user": f"{requester} ({requester_id})",
            "user_id": requester_id,
            "status": "active",
            "started_at": started_at.isoformat(),
            "duration_hours": duration_hours,
            "expires_at": expires_at,
        }
        aid = None
        try:
            aid = await _save_antiping_entry(archive_entry)
        except Exception:
            aid = None
        archive_entry["_archive_msg_id"] = aid

        anti_ping_map[requester_id] = {
            "archive_msg_id": aid,
            "status": "active",
            "started_at": archive_entry["started_at"],
            "duration_hours": duration_hours,
            "expires_at": expires_at,
        }

        panel_embed = discord.Embed(title="Anti-Ping Activated", color=discord.Color.blue())
        panel_embed.add_field(name="User", value=f"{requester} • {requester_id}", inline=False)
        panel_embed.add_field(name="Status", value="Active", inline=True)
        panel_embed.add_field(name="Started At", value=archive_entry["started_at"], inline=True)
        panel_embed.add_field(name="Duration (hours)", value=str(duration_hours) if duration_hours else "Indefinite", inline=True)
        if expires_at:
            panel_embed.add_field(name="Expires At", value=expires_at, inline=False)

        view = discord.ui.View()
        custom_prefix = f"antiping:{aid}:{requester_id}"
        view.add_item(discord.ui.Button(label="Pause", style=discord.ButtonStyle.secondary, custom_id=custom_prefix + ":pause"))
        view.add_item(discord.ui.Button(label="Stop", style=discord.ButtonStyle.danger, custom_id=custom_prefix + ":stop"))
        view.add_item(discord.ui.Button(label="Start/Resume", style=discord.ButtonStyle.success, custom_id=custom_prefix + ":start"))

        try:
            await interaction.followup.send(embed=panel_embed, view=view, ephemeral=True)
        except Exception:
            try:
                await interaction.response.send_message("Anti-ping activated.", ephemeral=True)
            except Exception:
                pass


class CloseReasonModal(discord.ui.Modal, title="Close Ticket Reason"):
    reason = discord.ui.TextInput(label="Reason for closing", style=discord.TextStyle.long, required=False, max_length=1000)

    def __init__(self, archive_id: Optional[int], requester_id: int, channel_id: int):
        super().__init__()
        self.archive_id = archive_id
        self.requester_id = requester_id
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        reason_text = self.reason.value.strip() if self.reason.value else "No reason provided"
        chan = interaction.client.get_channel(self.channel_id)
        if not isinstance(chan, discord.TextChannel):
            try:
                await interaction.response.send_message("Ticket channel not found.", ephemeral=True)
            except Exception:
                pass
            return

        details = None
        archive_id = self.archive_id
        arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
        archive_msg = None
        if archive_id and arch_ch:
            try:
                archive_msg = await arch_ch.fetch_message(archive_id)
                details = _extract_json_from_codeblock(archive_msg.content or "")
            except Exception:
                details = None

        if not details:
            # fallback search
            arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
            if arch_ch:
                try:
                    async for m in arch_ch.history(limit=2000):
                        p = _extract_json_from_codeblock(m.content or "")
                        if p and p.get("event_type") == TICKET_ARCHIVE_TYPE and p.get("channel_id") == chan.id:
                            details = p
                            archive_id = m.id
                            break
                except Exception:
                    pass

        details = details or {}
        details["status"] = "closed"
        details["close_reason"] = reason_text
        details["closed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        try:
            requester = interaction.client.get_user(self.requester_id) or await interaction.client.fetch_user(self.requester_id)
            details["closed_by"] = f"{requester} ({self.requester_id})"
        except Exception:
            details["closed_by"] = f"{self.requester_id}"

        if archive_id:
            try:
                await edit_archive_message(archive_id, details)
            except Exception:
                pass

        # Lock channel (deny send for default role)
        try:
            await chan.set_permissions(chan.guild.default_role, view_channel=True, send_messages=False)
        except Exception:
            pass

        owner_role = chan.guild.get_role(TICKET_TYPES.get(details.get("ticket_type"), {}).get("owner_role_id"))
        if owner_role:
            try:
                await chan.set_permissions(owner_role, view_channel=True, send_messages=False)
            except Exception:
                pass
        for rid in STAFF_ROLES:
            try:
                r = chan.guild.get_role(rid)
                if r:
                    await chan.set_permissions(r, view_channel=True, send_messages=False)
            except Exception:
                pass

        try:
            if chan.name.endswith("-open"):
                await chan.edit(name=chan.name.replace("-open", "-closed"))
            else:
                if not chan.name.endswith("-closed"):
                    await chan.edit(name=f"{chan.name}-closed")
        except Exception:
            pass

        try:
            logs_ch = await ensure_channel(TICKET_LOGS_CHANNEL_ID)
            if logs_ch:
                embed = discord.Embed(title=f"Ticket Closed — {chan.name}", color=discord.Color.red())
                embed.add_field(name="Ticket", value=chan.mention, inline=False)
                embed.add_field(name="Type", value=details.get("ticket_type", "N/A"), inline=True)
                embed.add_field(name="Opened By", value=details.get("opener", "N/A"), inline=True)
                embed.add_field(name="Opened At", value=details.get("created_at", "N/A"), inline=True)
                embed.add_field(name="Closed At", value=details.get("closed_at", "N/A"), inline=True)
                embed.add_field(name="Closed By", value=details.get("closed_by", "N/A"), inline=True)
                claimers = details.get("claimers", []) or []
                claimers_text = ", ".join([f"<@{c}>" for c in claimers]) if claimers else "None"
                embed.add_field(name="Claimers", value=claimers_text, inline=False)
                embed.add_field(name="Close Reason", value=details.get("close_reason", "No reason provided"), inline=False)
                await logs_ch.send(embed=embed)
        except Exception:
            pass

        try:
            await interaction.response.send_message("Ticket closed. Channel will be deleted.", ephemeral=True)
        except Exception:
            pass

        # Finally delete channel
        try:
            await chan.delete(reason="Ticket closed")
        except Exception:
            pass


# ====== AUTO RESPONDER (merged: anti-ping enforcement + original backup logic) =======
class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        # ignore bots
        if message.author.bot:
            return

        # Anti-ping enforcement (added)
        try:
            if isinstance(message.channel, discord.TextChannel):
                mentioned_ids = [m.id for m in message.mentions]
                if mentioned_ids:
                    for target_id in mentioned_ids:
                        entry = anti_ping_map.get(int(target_id))
                        if entry:
                            # check expiry
                            if _antiping_is_expired(entry):
                                try:
                                    aid = entry.get("archive_msg_id")
                                    if aid:
                                        arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                                        if arch_ch:
                                            try:
                                                msg = await arch_ch.fetch_message(aid)
                                                parsed = _extract_json_from_codeblock(msg.content or "")
                                                if parsed:
                                                    parsed["status"] = "stopped"
                                                    await edit_archive_message(aid, parsed)
                                            except Exception:
                                                pass
                                except Exception:
                                    pass
                                anti_ping_map.pop(int(target_id), None)
                                continue

                            # warn sender (do not delete by default)
                            try:
                                if message.reference:
                                    await message.channel.send(f"{message.author.mention}, that user has Anti-Ping enabled — please avoid @mentioning them in replies.", delete_after=12)
                                else:
                                    await message.channel.send(f"{message.author.mention}, that user has Anti-Ping enabled — do not ping them.", delete_after=12)
                            except Exception:
                                try:
                                    await message.channel.send("That user has Anti-Ping enabled — please do not ping them.", delete_after=12)
                                except Exception:
                                    pass
                            return
        except Exception:
            logger.exception("Anti-ping enforcement error")

        # --- Begin original AutoResponder logic (backup) ---
        content = message.content.strip().lower()

        # IA close/reopen handling (only in IA category)
        try:
            ch = message.channel
            if isinstance(ch, discord.TextChannel) and ch.category_id == IA_CATEGORY_ID:
                # -close command
                if content.startswith("-close"):
                    # Only IA role can run -close
                    member = message.author
                    if not any(r.id == IA_ROLE_ID for r in member.roles):
                        try:
                            await message.channel.send("You do not have permission to close this case.", delete_after=8)
                        except Exception:
                            pass
                        return

                    # fetch archive id from channel topic
                    topic = ch.topic or ""
                    match = re.search(r"ia_archive:(\d+)", topic)
                    archive_id = int(match.group(1)) if match else None

                    archive_msg = None
                    if archive_id:
                        archive_channel = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                        if archive_channel:
                            try:
                                archive_msg = await archive_channel.fetch_message(archive_id)
                            except Exception:
                                archive_msg = None

                    # if archive missing, try to find by channel id
                    details = None
                    if archive_msg:
                        details = _extract_json_from_codeblock(archive_msg.content or "")
                    else:
                        archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                        if archive_ch:
                            try:
                                async for m in archive_ch.history(limit=2000):
                                    p = _extract_json_from_codeblock(m.content or "")
                                    if p and p.get("event_type") == "ia_case" and p.get("channel_id") == ch.id:
                                        details = p
                                        archive_msg = m
                                        archive_id = m.id
                                        break
                            except Exception:
                                pass

                    if not details:
                        try:
                            await ch.send("Case archive record not found; closing anyway.", delete_after=8)
                        except Exception:
                            pass
                        details = {
                            "event_type": "ia_case",
                            "case_number": None,
                            "claimers": [],
                            "allowed_role_ids": [],
                            "allowed_member_ids": [],
                        }

                    # update claimers: include existing claimers + closer
                    claimers = details.get("claimers", []) or []
                    if member.id not in claimers:
                        claimers.append(member.id)
                    details["claimers"] = claimers
                    details["status"] = "closed"
                    details["closed_by"] = f"{member} ({member.id})"
                    details["closed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

                    # update archived message
                    if archive_id and details:
                        try:
                            await edit_archive_message(archive_id, details)
                        except Exception:
                            pass

                    # Lock the channel: deny send for allowed roles & members
                    # Deny send for everyone
                    try:
                        await ch.set_permissions(ch.guild.default_role, view_channel=True, send_messages=False)
                    except Exception:
                        pass

                    # Deny send for allowed roles and members
                    for rid in details.get("allowed_role_ids", []) or []:
                        try:
                            role = ch.guild.get_role(rid)
                            if role:
                                await ch.set_permissions(role, view_channel=True, send_messages=False)
                        except Exception:
                            pass
                    for mid in details.get("allowed_member_ids", []) or []:
                        try:
                            member_obj = ch.guild.get_member(mid)
                            if member_obj:
                                await ch.set_permissions(member_obj, view_channel=True, send_messages=False)
                        except Exception:
                            pass

                    # Rename channel to closed
                    try:
                        if ch.name.endswith("-open"):
                            await ch.edit(name=ch.name.replace("-open", "-closed"))
                        else:
                            # ensure suffix
                            if "-closed" not in ch.name:
                                await ch.edit(name=f"{ch.name}-closed")
                    except Exception:
                        pass

                    # Build closed embed as requested
                    offenders_text = f"{details.get('investigated', 'Unknown')}" if details.get("investigated") else "Unknown"
                    claimers_ids = details.get("claimers", []) or []
                    claimers_mentions = []
                    for cid in claimers_ids:
                        try:
                            mobj = ch.guild.get_member(cid)
                            if mobj:
                                claimers_mentions.append(str(mobj))
                            else:
                                claimers_mentions.append(str(cid))
                        except Exception:
                            claimers_mentions.append(str(cid))
                    claimed_text = ", ".join(claimers_mentions) if claimers_mentions else "None"

                    close_embed = discord.Embed(title="🔒 Case Closed", description=":isrp: This case has been closed.", color=discord.Color.dark_red())
                    close_embed.add_field(name="Offender", value=offenders_text, inline=False)
                    close_embed.add_field(name="Claimed", value=claimed_text, inline=False)
                    close_embed.add_field(name="Notice", value="DO NOT TYPE HERE. Failure to comply will lead to disciplinary action.\nTo reopen this case please type `-reopen`", inline=False)

                    try:
                        await ch.send(embed=close_embed)
                    except Exception:
                        pass

                    return

                # -reopen command
                if content.startswith("-reopen"):
                    member = message.author
                    if not any(r.id == IA_ROLE_ID for r in member.roles):
                        try:
                            await message.channel.send("You do not have permission to reopen this case.", delete_after=8)
                        except Exception:
                            pass
                        return

                    ch = message.channel
                    # fetch archive id
                    topic = ch.topic or ""
                    match = re.search(r"ia_archive:(\d+)", topic)
                    archive_id = int(match.group(1)) if match else None

                    archive_msg = None
                    details = None
                    if archive_id:
                        archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                        if archive_ch:
                            try:
                                archive_msg = await archive_ch.fetch_message(archive_id)
                                details = _extract_json_from_codeblock(archive_msg.content or "")
                            except Exception:
                                archive_msg = None
                                details = None

                    if not details:
                        # try to search by channel id
                        archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                        if archive_ch:
                            try:
                                async for m in archive_ch.history(limit=2000):
                                    p = _extract_json_from_codeblock(m.content or "")
                                    if p and p.get("event_type") == "ia_case" and p.get("channel_id") == ch.id:
                                        details = p
                                        archive_msg = m
                                        archive_id = m.id
                                        break
                            except Exception:
                                pass

                    if not details:
                        try:
                            await ch.send("Case archive record not found; reopening anyway.", delete_after=8)
                        except Exception:
                            pass
                        details = {"allowed_role_ids": [], "allowed_member_ids": []}

                    # set status open
                    details["status"] = "open"
                    details["closed_by"] = None
                    details["closed_at"] = None
                    # update archive
                    if archive_id and details:
                        try:
                            await edit_archive_message(archive_id, details)
                        except Exception:
                            pass

                    # Restore send permissions for allowed roles/members
                    try:
                        await ch.set_permissions(ch.guild.default_role, view_channel=False, send_messages=False)
                    except Exception:
                        pass
                    for rid in details.get("allowed_role_ids", []) or []:
                        try:
                            role = ch.guild.get_role(rid)
                            if role:
                                await ch.set_permissions(role, view_channel=True, send_messages=True)
                        except Exception:
                            pass
                    for mid in details.get("allowed_member_ids", []) or []:
                        try:
                            mobj = ch.guild.get_member(mid)
                            if mobj:
                                await ch.set_permissions(mobj, view_channel=True, send_messages=True)
                        except Exception:
                            pass

                    # Rename channel to open
                    try:
                        if ch.name.endswith("-closed"):
                            await ch.edit(name=ch.name.replace("-closed", "-open"))
                        else:
                            if "-open" not in ch.name:
                                await ch.edit(name=f"{ch.name}-open")
                    except Exception:
                        pass

                    # Announcement
                    try:
                        await ch.send(f"This case has been reopened by {member.mention}")
                    except Exception:
                        pass

                    return
        except Exception:
            # don't block other responders if IA logic errors
            pass

        # Other message-based commands (existing auto responder behavior)
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

        # Command logging for message-based commands and '-' triggers (embed + Expand button backed by Discord storage for infractions/promotions only)
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
                    # send embed (no archive for message_command since only infractions/promotions/ia_case are archived)
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


# ====== SERVER WARNINGS and ticket handling (kept as backup) =======
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
            # This will post embed to BOD_ALERT_CHANNEL_ID but will NOT archive (event_type not infract/promote/ia_case)
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


# ====== Interaction handling (component presses, expand, IA claim) =======
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

            # Anti-ping control buttons: format antiping:{archive_id}:{owner_id}:action
            if cid and isinstance(cid, str) and cid.startswith("antiping:"):
                parts = cid.split(":")
                # expected: ["antiping", archive_id, owner_id, action]
                if len(parts) >= 4:
                    try:
                        archive_id = int(parts[1])
                    except Exception:
                        archive_id = None
                    try:
                        owner_id = int(parts[2])
                    except Exception:
                        owner_id = None
                    action = parts[3]
                else:
                    archive_id = None
                    owner_id = None
                    action = None

                # only the owner may control their anti-ping (or BOD)
                allowed = False
                try:
                    if interaction.user.id == owner_id:
                        allowed = True
                    else:
                        # allow BOD to manage others
                        if any(r.id == BOD_ROLE_ID for r in getattr(interaction.user, "roles", [])):
                            allowed = True
                except Exception:
                    allowed = False

                if not allowed:
                    try:
                        await interaction.response.send_message("You are not authorized to control this Anti-Ping.", ephemeral=True)
                    except Exception:
                        pass
                    return

                # fetch archive message and parsed data
                arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                parsed = None
                if archive_id and arch_ch:
                    try:
                        am = await arch_ch.fetch_message(archive_id)
                        parsed = _extract_json_from_codeblock(am.content or "")
                    except Exception:
                        parsed = None

                if not parsed:
                    # try to find by user id
                    arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                    if arch_ch:
                        try:
                            async for m in arch_ch.history(limit=2000):
                                p = _extract_json_from_codeblock(m.content or "")
                                if p and p.get("event_type") == ANTIPING_ARCHIVE_TYPE and int(p.get("user_id", -1)) == owner_id:
                                    parsed = p
                                    archive_id = m.id
                                    break
                        except Exception:
                            parsed = None

                if not parsed:
                    try:
                        await interaction.response.send_message("Anti-Ping record not found.", ephemeral=True)
                    except Exception:
                        pass
                    return

                # Apply action
                if action == "pause":
                    parsed["status"] = "paused"
                    if archive_id:
                        await edit_archive_message(archive_id, parsed)
                    anti_ping_map.pop(owner_id, None)
                    try:
                        await interaction.response.send_message("Anti-Ping paused.", ephemeral=True)
                    except Exception:
                        pass
                    return
                if action == "stop":
                    parsed["status"] = "stopped"
                    if archive_id:
                        await edit_archive_message(archive_id, parsed)
                    anti_ping_map.pop(owner_id, None)
                    try:
                        await interaction.response.send_message("Anti-Ping stopped.", ephemeral=True)
                    except Exception:
                        pass
                    return
                if action == "start":
                    parsed["status"] = "active"
                    # update started_at and expires if duration set
                    now = datetime.now(timezone.utc)
                    parsed["started_at"] = now.isoformat()
                    duration = parsed.get("duration_hours")
                    if duration:
                        try:
                            dur = float(duration)
                            parsed["expires_at"] = (now + timedelta(hours=dur)).isoformat()
                        except Exception:
                            parsed["expires_at"] = None
                    else:
                        parsed["expires_at"] = None
                    if archive_id:
                        await edit_archive_message(archive_id, parsed)
                    anti_ping_map[owner_id] = {
                        "archive_msg_id": archive_id,
                        "status": "active",
                        "started_at": parsed.get("started_at"),
                        "duration_hours": parsed.get("duration_hours"),
                        "expires_at": parsed.get("expires_at"),
                    }
                    try:
                        await interaction.response.send_message("Anti-Ping started/resumed.", ephemeral=True)
                    except Exception:
                        pass
                    return

            # IA Claim button handling
            if cid and isinstance(cid, str) and cid.startswith("ia_claim:"):
                try:
                    chan = interaction.channel
                    if not isinstance(chan, discord.TextChannel):
                        await interaction.response.send_message("Claim can only be used inside case channels.", ephemeral=True)
                        return
                    # find archive id in topic
                    topic = chan.topic or ""
                    match = re.search(r"ia_archive:(\d+)", topic)
                    archive_id = int(match.group(1)) if match else None
                    archive_msg = None
                    details = None
                    if archive_id:
                        archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                        if archive_ch:
                            try:
                                archive_msg = await archive_ch.fetch_message(archive_id)
                                details = _extract_json_from_codeblock(archive_msg.content or "")
                            except Exception:
                                archive_msg = None
                                details = None

                    # fallback: search for archive by channel id
                    if not details:
                        archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                        if archive_ch:
                            try:
                                async for m in archive_ch.history(limit=2000):
                                    p = _extract_json_from_codeblock(m.content or "")
                                    if p and p.get("event_type") == "ia_case" and p.get("channel_id") == chan.id:
                                        details = p
                                        archive_msg = m
                                        archive_id = m.id
                                        break
                            except Exception:
                                pass

                    if not details:
                        await interaction.response.send_message("Case archive not found (cannot register claim).", ephemeral=True)
                        return

                    claimers = details.get("claimers", []) or []
                    user_id = interaction.user.id
                    if user_id not in claimers:
                        claimers.append(user_id)
                        details["claimers"] = claimers
                        # update archive message
                        if archive_id:
                            try:
                                await edit_archive_message(archive_id, details)
                            except Exception:
                                pass

                    # Announce claim in the case channel
                    try:
                        ann_embed = discord.Embed(description=f"{interaction.user.mention} has claimed this case.", color=discord.Color.blue())
                        await chan.send(embed=ann_embed)
                    except Exception:
                        pass

                    await interaction.response.send_message("You claimed the case.", ephemeral=True)
                except Exception:
                    try:
                        await interaction.response.send_message("Failed to register claim.", ephemeral=True)
                    except Exception:
                        pass
                return

            # Expand button handling (existing)
            if cid and isinstance(cid, str) and cid.startswith("expand:"):
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
startup_import_task = None


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")

    # load anti-ping entries (so enforcement works immediately)
    try:
        await _load_antiping_from_archive()
    except Exception:
        logger.exception("Failed to load anti-ping on startup")

    # add cogs safely (await if needed)
    try:
        res = bot.add_cog(StaffCommands(bot))
        if inspect.isawaitable(res):
            await res
    except Exception:
        pass

    try:
        res = bot.add_cog(PublicCommands(bot))
        if inspect.isawaitable(res):
            await res
    except Exception:
        pass

    try:
        res = bot.add_cog(AutoResponder(bot))
        if inspect.isawaitable(res):
            await res
    except Exception:
        pass

    # add command groups if not present (ensure infraction/promotion/ia groups registered)
    try:
        existing = [c.name for c in bot.tree.walk_commands()]
        if "infraction" not in existing:
            bot.tree.add_command(InfractionGroup())
        if "promotion" not in existing:
            bot.tree.add_command(PromotionGroup())
        if "ia" not in existing:
            bot.tree.add_command(IAGroup())
    except Exception:
        pass

    # Ensure commands are only synced once per bot session
    if not getattr(bot, "app_commands_synced", False):
        try:
            guild_obj = discord.Object(id=MAIN_GUILD_ID)
            # copy globals to guild (so slash commands appear instantly)
            try:
                bot.tree.copy_global_to(guild=guild_obj)
            except Exception:
                # ignore if not supported in environment
                pass
            # sync and await properly
            sync_res = bot.tree.sync(guild=guild_obj)
            if inspect.isawaitable(sync_res):
                await sync_res
            bot.app_commands_synced = True
            logger.info("Slash commands synced.")
            # Log currently registered commands for debugging
            try:
                for c in bot.tree.walk_commands():
                    logger.info(f"Registered app command: {c.name}")
            except Exception:
                pass
        except Exception:
            logger.exception("Failed to sync slash commands")

    # Run a safe, limited startup import of old infractions (non-blocking)
    global startup_import_task
    if startup_import_task is None:
        async def _startup_import():
            try:
                logger.info("Starting limited startup infraction import (safe).")
                res = await scan_and_archive_infractions(limit=300)
                if res.get("available"):
                    logger.info(f"Startup import finished: {res}")
                else:
                    logger.info("Startup import skipped: channels not available.")
            except Exception:
                logger.exception("Startup import failed.")

        startup_import_task = asyncio.create_task(_startup_import())


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
