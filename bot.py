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

# Ticket & support config
SUPPORT_CHANNEL_ID = 1371272558221066261
TICKET_CATEGORY_ID = 1450278544008679425
TICKET_LOGS_CHANNEL_ID = 1371272560192258130

# Mod archive (persistent storage inside Discord)
MOD_ARCHIVE_CHANNEL_ID = 1459286015905890345

# Internal Affairs related IDs
IA_ROLE_ID = 1404679512276602881
IA_AGENT_ROLE_ID = 1400189498087964734
IA_SUPERVISOR_ROLE_ID = 1400189341590093967

# Ticket owning roles per type
PARTNERSHIP_ROLE_ID = 1371272556987940903
HR_ROLE_ID = BOD_ROLE_ID
GENERAL_SUPPORT_ROLE_ID = 1373338084195958957

# Evidence channel used in IA embed note
EVIDENCE_CHANNEL_ID = 1404677593856348301

# Banners
SUPPORT_EMBED_BANNER = "https://media.discordapp.net/attachments/1449498805517942805/1449498852662181888/image.png"
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
# Anti-ping in-memory map + helpers
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


# ------------------------
# Shared utilities & types
# ------------------------
class ExpandView(discord.ui.View):
    def __init__(self, archive_message_id: Optional[int]):
        super().__init__(timeout=None)
        self.archive_message_id = archive_message_id
        if archive_message_id and isinstance(archive_message_id, int) and archive_message_id > 0:
            custom_id = f"expand:{archive_message_id}"
            self.add_item(discord.ui.Button(label="Expand", style=discord.ButtonStyle.primary, custom_id=custom_id))


def is_staff(interaction: discord.Interaction) -> bool:
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    return any(role.id in STAFF_ROLES for role in user.roles)


def is_bod(interaction: discord.Interaction) -> bool:
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    return any(role.id == BOD_ROLE_ID for role in user.roles)


def is_ia(interaction: discord.Interaction) -> bool:
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    return any(role.id == IA_ROLE_ID for role in user.roles)


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
    if not content:
        return None
    content = content.strip()
    if content.startswith("```") and content.endswith("```"):
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
        m = re.search(r"\{.*\}", inner, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


async def archive_details_to_mod_channel(details: Dict[str, Any]) -> Optional[int]:
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


async def send_embed_with_expand(target_channel: discord.abc.GuildChannel | discord.TextChannel, embed: discord.Embed, details: Dict[str, Any]):
    try:
        event_type = details.get("event_type") if isinstance(details, dict) else None
        if event_type in ("infract", "promote", "ia_case", "ticket", ANTIPING_ARCHIVE_TYPE):
            archive_msg_id = await archive_details_to_mod_channel(details)
            if archive_msg_id:
                view = ExpandView(archive_msg_id)
                try:
                    await target_channel.send(embed=embed, view=view)
                except Exception:
                    try:
                        await target_channel.send(embed=embed)
                    except Exception:
                        pass
            else:
                try:
                    await target_channel.send(embed=embed)
                except Exception:
                    pass
        else:
            try:
                await target_channel.send(embed=embed)
            except Exception:
                pass
    except Exception:
        pass


async def find_archived_infractions_in_mod(limit: int = 1000) -> List[Dict[str, Any]]:
    archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    results: List[Dict[str, Any]] = []
    if not archive_ch:
        return results
    try:
        async for m in archive_ch.history(limit=limit):
            parsed = _extract_json_from_codeblock(m.content or "")
            if parsed:
                parsed["_archive_message_id"] = m.id
                results.append(parsed)
    except Exception:
        pass
    return results


async def archive_has_code(code: Any, lookback: int = 200) -> bool:
    archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not archive_ch:
        return False
    try:
        async for m in archive_ch.history(limit=lookback):
            parsed = _extract_json_from_codeblock(m.content or "")
            if parsed and parsed.get("event_type") == "infract":
                if str(parsed.get("code")) == str(code):
                    return True
                if parsed.get("infraction_message_id") and parsed.get("infraction_message_id") == code:
                    return True
    except Exception:
        pass
    return False


# Shared scanning helper (kept from earlier merged code)
async def scan_and_archive_infractions(limit: int = 500) -> Dict[str, int]:
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


# ------------------------
# Ticket / UI helpers
# ------------------------
TICKET_TYPES = {
    "partnership": {
        "title": "Partnership Ticket",
        "description": "Click on the button below to open a Partnership ticket!",
        "role_ping": PARTNERSHIP_ROLE_ID,
        "owner_role_id": PARTNERSHIP_ROLE_ID,
    },
    "hr": {
        "title": "HR Ticket",
        "description": "Click on the button below to open a HR ticket!",
        "role_ping": HR_ROLE_ID,
        "owner_role_id": HR_ROLE_ID,
    },
    "general": {
        "title": "Support Ticket",
        "description": "Click on the button below to open a Support ticket!",
        "role_ping": GENERAL_SUPPORT_ROLE_ID,
        "owner_role_id": GENERAL_SUPPORT_ROLE_ID,
    },
}

TICKET_UI_ARCHIVE_TYPE = "ticket_ui"
TICKET_ARCHIVE_TYPE = "ticket"


def sanitize_channel_name(display_name: str) -> str:
    name = display_name.lower().replace(" ", "-")
    name = re.sub(r"[^a-z0-9\-]", "", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    if not name:
        name = "user"
    return name[:80]


async def ensure_ticket_ui_messages():
    support_ch = await ensure_channel(SUPPORT_CHANNEL_ID)
    if not support_ch:
        logger.warning("Support channel not available for ticket UI creation.")
        return

    archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    existing_ui = {}
    archive_msg_id = None
    if archive_ch:
        try:
            async for m in archive_ch.history(limit=1000):
                parsed = _extract_json_from_codeblock(m.content or "")
                if parsed and parsed.get("event_type") == TICKET_UI_ARCHIVE_TYPE:
                    existing_ui = parsed.get("ui", {}) or {}
                    archive_msg_id = m.id
                    break
        except Exception:
            pass

    ui_map = dict(existing_ui)
    changed = False
    for tkey, tconf in TICKET_TYPES.items():
        mid = ui_map.get(tkey)
        ok = False
        if mid:
            try:
                m = await support_ch.fetch_message(int(mid))
                ok = True
            except Exception:
                ok = False

        if not ok:
            embed = discord.Embed(title=tconf["title"], description=tconf["description"], color=discord.Color.blurple())
            embed.set_image(url=SUPPORT_EMBED_BANNER)
            view = discord.ui.View()
            btn = discord.ui.Button(label=f"Open {tconf['title']}", style=discord.ButtonStyle.primary, custom_id=f"ticket_create:{tkey}")
            view.add_item(btn)
            try:
                sent = await support_ch.send(embed=embed, view=view)
                ui_map[tkey] = sent.id
                changed = True
            except Exception:
                logger.exception(f"Failed to send ticket UI for {tkey}")

    if changed and archive_ch:
        record = {
            "event_type": TICKET_UI_ARCHIVE_TYPE,
            "ui": ui_map,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
        try:
            if archive_msg_id:
                await edit_archive_message(archive_msg_id, record)
            else:
                await archive_details_to_mod_channel(record)
        except Exception:
            pass


async def create_ticket_channel_for(user: discord.Member, ticket_type: str, opener: discord.Member):
    guild = user.guild
    if not guild:
        return None, None

    sanitized = sanitize_channel_name(user.display_name or user.name)
    last4 = str(user.id)[-4:]
    channel_name = f"{sanitized}-{ticket_type}-{last4}"

    category = discord.utils.get(guild.categories, id=TICKET_CATEGORY_ID)
    overwrites: Dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {}
    everyone_role = guild.default_role
    overwrites[everyone_role] = discord.PermissionOverwrite(view_channel=False)

    overwrites[user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
    overwrites[opener] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)

    owner_role_id = TICKET_TYPES[ticket_type]["owner_role_id"]
    owner_role = guild.get_role(owner_role_id)
    if owner_role:
        overwrites[owner_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    for rid in STAFF_ROLES:
        r = guild.get_role(rid)
        if r:
            overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    me = guild.me or guild.get_member(bot.user.id)
    if me:
        overwrites[me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True, manage_channels=True)

    try:
        chan = await guild.create_text_channel(channel_name, category=category, overwrites=overwrites, reason=f"Ticket opened by {opener}")
    except Exception:
        logger.exception("Failed to create ticket channel")
        return None, None

    conf = TICKET_TYPES[ticket_type]
    role_ping = conf.get("role_ping")
    ping_text = f"<@&{role_ping}>" if role_ping else ""
    # Send a plain content ping so the role actually gets notified
    try:
        if ping_text:
            await chan.send(content=ping_text)
    except Exception:
        pass

    initial_embed = discord.Embed(title=conf["title"], description="Hello! Thank you for contacting the Iowa State Roleplay Support Team.\nPlease state the reason for opening the ticket, and a support member will respond when they're available!", color=discord.Color.green())
    initial_embed.set_image(url=SUPPORT_EMBED_BANNER)
    view = discord.ui.View()
    claim_btn = discord.ui.Button(label="Claim", style=discord.ButtonStyle.secondary, custom_id=f"ticket_claim:{chan.id}")
    close_btn = discord.ui.Button(label="Close", style=discord.ButtonStyle.danger, custom_id=f"ticket_close:{chan.id}")
    view.add_item(claim_btn)
    view.add_item(close_btn)

    try:
        sent = await chan.send(embed=initial_embed, view=view)
    except Exception:
        sent = None

    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    details = {
        "event_type": TICKET_ARCHIVE_TYPE,
        "ticket_type": ticket_type,
        "channel_id": chan.id,
        "channel_name": chan.name,
        "opener": f"{user} ({user.id})",
        "opener_id": user.id,
        "opened_by": f"{opener} ({opener.id})",
        "opened_by_id": opener.id,
        "created_at": created_at,
        "status": "open",
        "claimers": [],
        "close_reason": None,
        "closed_at": None,
        "closed_by": None,
        "inactivity_pinged_at": None,
    }
    archive_msg_id = None
    if await ensure_channel(MOD_ARCHIVE_CHANNEL_ID):
        archive_msg_id = await archive_details_to_mod_channel(details)
        try:
            await chan.edit(topic=f"ticket_archive:{archive_msg_id} type:{ticket_type}")
        except Exception:
            pass

    return chan, archive_msg_id


# ------------------------
# Anti-ping persistence helpers
# ------------------------
async def _load_antiping_from_archive():
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
# Modals
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
            # fallback
            try:
                async for m in (await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)).history(limit=2000):
                    p = _extract_json_from_codeblock(m.content or "")
                    if p and p.get("event_type") == TICKET_ARCHIVE_TYPE and p.get("channel_id") == chan.id:
                        details = p
                        archive_id = m.id
                        break
            except Exception:
                details = details or {}

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


# ====== AUTO RESPONDER (enforcement + basic message handlers) =======
class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        # ignore bots
        if message.author.bot:
            return

        # Anti-ping enforcement
        try:
            if not isinstance(message.channel, discord.TextChannel):
                return
            mentioned_ids = [m.id for m in message.mentions]
            if mentioned_ids:
                for target_id in mentioned_ids:
                    entry = anti_ping_map.get(int(target_id))
                    if entry:
                        # expiry
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

        # Existing message handlers (IA close/reopen, -inactive, -partnerinfo, etc.) would be here.
        # This merged file focuses on tickets/anti-ping; keep rest of AutoResponder logic as needed.

        await bot.process_commands(message)


# -------------------------
# Ticket inactivity checking
# -------------------------
INACTIVITY_THRESHOLD_HOURS = 6
INACTIVITY_REPEAT_HOURS = 24


async def _check_ticket_inactivity_once():
    arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not arch_ch:
        return
    now = datetime.now(timezone.utc)
    try:
        async for m in arch_ch.history(limit=2000):
            parsed = _extract_json_from_codeblock(m.content or "")
            if not parsed:
                continue
            if parsed.get("event_type") != TICKET_ARCHIVE_TYPE:
                continue
            if parsed.get("status") != "open":
                continue
            channel_id = parsed.get("channel_id")
            opener_id = parsed.get("opener_id")
            archive_msg_id = m.id
            inactivity_pinged_str = parsed.get("inactivity_pinged_at")
            inactivity_pinged_at = None
            if inactivity_pinged_str:
                try:
                    inactivity_pinged_at = datetime.fromisoformat(inactivity_pinged_str)
                except Exception:
                    inactivity_pinged_at = None

            try:
                chan = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            except Exception:
                chan = None

            if not isinstance(chan, discord.TextChannel):
                continue

            try:
                last_msg = None
                async for msg in chan.history(limit=1, oldest_first=False):
                    last_msg = msg
                    break
                if last_msg:
                    last_time = last_msg.created_at.replace(tzinfo=timezone.utc) if last_msg.created_at.tzinfo is None else last_msg.created_at.astimezone(timezone.utc)
                else:
                    created_at_str = parsed.get("created_at")
                    try:
                        last_time = datetime.fromisoformat(created_at_str) if created_at_str else datetime.now(timezone.utc)
                    except Exception:
                        last_time = datetime.now(timezone.utc)
            except Exception:
                continue

            hours_idle = (now - last_time).total_seconds() / 3600.0
            if hours_idle >= INACTIVITY_THRESHOLD_HOURS:
                if inactivity_pinged_at and (now - inactivity_pinged_at).total_seconds() < INACTIVITY_REPEAT_HOURS * 3600:
                    continue

                mention_text = f"<@{opener_id}>" if opener_id else ""
                try:
                    if mention_text:
                        await chan.send(content=mention_text)
                    embed = discord.Embed(
                        title="⚠️ Ticket Inactivity",
                        description="This ticket will be automatically closed within 24 hours of inactivity.",
                        color=discord.Color.orange()
                    )
                    await chan.send(embed=embed)
                except Exception:
                    pass

                parsed["inactivity_pinged_at"] = now.isoformat()
                try:
                    await edit_archive_message(archive_msg_id, parsed)
                except Exception:
                    pass

    except Exception:
        logger.exception("ticket inactivity check failed")


async def ticket_inactivity_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await _check_ticket_inactivity_once()
        except Exception:
            logger.exception("ticket_inactivity_loop error")
        await asyncio.sleep(1800)


# ------------------------
# Interaction handling (tickets, antiping, IA claim, expand)
# ------------------------
@bot.event
async def on_interaction(interaction: discord.Interaction):
    try:
        if interaction.type == discord.InteractionType.component:
            cid = None
            try:
                if isinstance(interaction.data, dict):
                    cid = interaction.data.get("custom_id") or interaction.data.get("customID") or interaction.data.get("component_type")
            except Exception:
                cid = None

            # Ticket create (support UI)
            if cid and isinstance(cid, str) and cid.startswith("ticket_create:"):
                tkey = cid.split(":", 1)[1]
                await interaction.response.defer(ephemeral=True)
                opener_member = interaction.user
                chan, archive_id = await create_ticket_channel_for(opener_member, tkey, opener_member)
                if chan:
                    try:
                        await interaction.followup.send(f"Ticket opened: {chan.mention}", ephemeral=True)
                    except Exception:
                        pass
                else:
                    try:
                        await interaction.followup.send("Failed to open ticket.", ephemeral=True)
                    except Exception:
                        pass
                return

            # Ticket claim
            if cid and isinstance(cid, str) and cid.startswith("ticket_claim:"):
                try:
                    channel_id = int(cid.split(":", 1)[1])
                except Exception:
                    channel_id = None
                if channel_id != interaction.channel.id:
                    await interaction.response.send_message("This button is not for this channel.", ephemeral=True)
                    return

                details = await find_ticket_archive_by_channel(interaction.channel)
                if not details:
                    await interaction.response.send_message("Ticket metadata not found.", ephemeral=True)
                    return
                archive_id = details.get("_archive_message_id")
                claimers: List[int] = details.get("claimers", []) or []
                user_id = interaction.user.id

                if user_id == details.get("opener_id"):
                    await interaction.response.send_message("You cannot claim your own ticket.", ephemeral=True)
                    return

                if len(claimers) == 0:
                    claimers.append(user_id)
                    details["claimers"] = claimers
                    if archive_id:
                        await edit_archive_message(archive_id, details)
                    try:
                        await interaction.channel.send(embed=discord.Embed(description=f"{interaction.user.mention} has claimed this ticket.", color=discord.Color.blue()))
                    except Exception:
                        pass
                    await interaction.response.send_message("You claimed this ticket.", ephemeral=True)
                    return

                if user_id in claimers:
                    claimers.remove(user_id)
                    details["claimers"] = claimers
                    if archive_id:
                        await edit_archive_message(archive_id, details)
                    try:
                        await interaction.channel.send(embed=discord.Embed(description=f"{interaction.user.mention} has unclaimed this ticket.", color=discord.Color.orange()))
                    except Exception:
                        pass
                    await interaction.response.send_message("You unclaimed this ticket.", ephemeral=True)
                    return

                first_claimer_id = claimers[0]
                first_claimer = interaction.channel.guild.get_member(first_claimer_id) if interaction.channel.guild else None
                if not first_claimer:
                    claimers.append(user_id)
                    details["claimers"] = claimers
                    if archive_id:
                        await edit_archive_message(archive_id, details)
                    try:
                        await interaction.channel.send(embed=discord.Embed(description=f"{interaction.user.mention} has been added as a claimer (no approver available).", color=discord.Color.blue()))
                    except Exception:
                        pass
                    await interaction.response.send_message("You claimed this ticket.", ephemeral=True)
                    return

                approval_view = discord.ui.View(timeout=1800)
                new_claimer_id = user_id
                approve_id = f"ticket_approve:{archive_id}:{new_claimer_id}"
                deny_id = f"ticket_deny:{archive_id}:{new_claimer_id}"
                approval_view.add_item(discord.ui.Button(style=discord.ButtonStyle.success, label="Approve", custom_id=approve_id))
                approval_view.add_item(discord.ui.Button(style=discord.ButtonStyle.danger, label="Deny", custom_id=deny_id))
                try:
                    await interaction.channel.send(content=f"{first_claimer.mention}, {interaction.user.mention} requests to claim this ticket. Allow?", view=approval_view)
                except Exception:
                    pass
                await interaction.response.send_message("Requested permission from the original claimer. They must approve to add you.", ephemeral=True)
                return

            # Approve / Deny claim
            if cid and isinstance(cid, str) and (cid.startswith("ticket_approve:") or cid.startswith("ticket_deny:")):
                parts = cid.split(":")
                action = parts[0]
                try:
                    archive_id = int(parts[1])
                    new_claimer_id = int(parts[2])
                except Exception:
                    archive_id = None
                    new_claimer_id = None

                arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                archive_msg = None
                details = None
                if archive_id and arch_ch:
                    try:
                        archive_msg = await arch_ch.fetch_message(archive_id)
                        details = _extract_json_from_codeblock(archive_msg.content or "")
                    except Exception:
                        details = None

                if not details and isinstance(interaction.channel, discord.TextChannel):
                    details = await find_ticket_archive_by_channel(interaction.channel)

                if not details:
                    await interaction.response.send_message("Ticket archive not found.", ephemeral=True)
                    return

                claimers = details.get("claimers", []) or []
                if not claimers:
                    await interaction.response.send_message("No claimer to approve request.", ephemeral=True)
                    return

                first_claimer = claimers[0]
                if interaction.user.id != first_claimer:
                    await interaction.response.send_message("Only the original claimer can approve or deny this request.", ephemeral=True)
                    return

                if action == "ticket_approve":
                    if new_claimer_id not in claimers:
                        claimers.append(new_claimer_id)
                        details["claimers"] = claimers
                        if archive_id:
                            await edit_archive_message(archive_id, details)
                        try:
                            await interaction.channel.send(embed=discord.Embed(description=f"<@{new_claimer_id}> has been approved to claim this ticket by {interaction.user.mention}.", color=discord.Color.green()))
                        except Exception:
                            pass
                    await interaction.response.send_message("Approved.", ephemeral=True)
                    return
                else:
                    try:
                        await interaction.channel.send(embed=discord.Embed(description=f"{interaction.user.mention} denied the claim request for <@{new_claimer_id}>.", color=discord.Color.red()))
                    except Exception:
                        pass
                    await interaction.response.send_message("Denied.", ephemeral=True)
                    return

            # Ticket close: open modal or request approval flow
            if cid and isinstance(cid, str) and cid.startswith("ticket_close:"):
                try:
                    channel_id = int(cid.split(":", 1)[1])
                except Exception:
                    channel_id = None
                if channel_id != interaction.channel.id:
                    await interaction.response.send_message("This button is not for this channel.", ephemeral=True)
                    return

                details = await find_ticket_archive_by_channel(interaction.channel)
                if not details:
                    await interaction.response.send_message("Ticket metadata not found.", ephemeral=True)
                    return
                archive_id = details.get("_archive_message_id")
                claimers = details.get("claimers", []) or []
                requester_id = interaction.user.id

                allowed_role_id = TICKET_TYPES[details.get("ticket_type")]["owner_role_id"]
                has_owner_role = any(r.id == allowed_role_id for r in interaction.user.roles)

                if has_owner_role:
                    modal = CloseReasonModal(archive_id=archive_id, requester_id=requester_id, channel_id=interaction.channel.id)
                    try:
                        await interaction.response.send_modal(modal)
                    except Exception:
                        await interaction.response.send_message("Failed to show close modal.", ephemeral=True)
                    return

                if len(claimers) == 0:
                    modal = CloseReasonModal(archive_id=archive_id, requester_id=requester_id, channel_id=interaction.channel.id)
                    try:
                        await interaction.response.send_modal(modal)
                    except Exception:
                        await interaction.response.send_message("Failed to show close modal.", ephemeral=True)
                    return

                first_claimer_id = claimers[0]
                if requester_id == first_claimer_id:
                    modal = CloseReasonModal(archive_id=archive_id, requester_id=requester_id, channel_id=interaction.channel.id)
                    try:
                        await interaction.response.send_modal(modal)
                    except Exception:
                        await interaction.response.send_message("Failed to show close modal.", ephemeral=True)
                    return

                # Request approval from first claimer
                class ApprovalRequestModal(discord.ui.Modal, title="Request Close — Reason"):
                    reason = discord.ui.TextInput(label="Reason for closing", style=discord.TextStyle.long, required=False, max_length=1000)

                    def __init__(self, archive_id: Optional[int], requester_id: int, first_claimer_id: int, channel_id: int):
                        super().__init__()
                        self.archive_id = archive_id
                        self.requester_id = requester_id
                        self.first_claimer_id = first_claimer_id
                        self.channel_id = channel_id

                    async def on_submit(self, modal_interaction: discord.Interaction):
                        reason_value = self.reason.value.strip() if self.reason.value else "No reason provided"
                        chan = modal_interaction.client.get_channel(self.channel_id)
                        if not isinstance(chan, discord.TextChannel):
                            try:
                                await modal_interaction.response.send_message("Ticket channel not found.", ephemeral=True)
                            except Exception:
                                pass
                            return

                        details_local = await find_ticket_archive_by_channel(chan)
                        archive_local_id = details_local.get("_archive_message_id") if details_local else self.archive_id

                        approver_id = self.first_claimer_id
                        approver_member = chan.guild.get_member(approver_id) if chan.guild else None
                        if not approver_member:
                            await modal_interaction.response.send_message("Approver (original claimer) not found — cannot request approval.", ephemeral=True)
                            return

                        pending = {
                            "requester_id": self.requester_id,
                            "reason": reason_value,
                            "requested_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                        }
                        try:
                            arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                            if arch_ch and archive_local_id:
                                msg = await arch_ch.fetch_message(archive_local_id)
                                parsed = _extract_json_from_codeblock(msg.content or "")
                                if parsed:
                                    parsed["pending_close_request"] = pending
                                    await edit_archive_message(archive_local_id, parsed)
                        except Exception:
                            pass

                        view = discord.ui.View(timeout=1800)
                        approve_id = f"ticket_close_approve:{archive_local_id}:{self.requester_id}"
                        deny_id = f"ticket_close_deny:{archive_local_id}:{self.requester_id}"
                        view.add_item(discord.ui.Button(style=discord.ButtonStyle.success, label="Approve", custom_id=approve_id))
                        view.add_item(discord.ui.Button(style=discord.ButtonStyle.danger, label="Deny", custom_id=deny_id))
                        try:
                            await chan.send(content=f"{approver_member.mention}, {modal_interaction.user.mention} has requested to close this ticket. Reason: {reason_value}\nOnly you may Approve or Deny.", view=view)
                        except Exception:
                            pass

                        try:
                            await modal_interaction.response.send_message("Close request sent to the claimer(s). They must approve to close.", ephemeral=True)
                        except Exception:
                            pass

                modal2 = ApprovalRequestModal(archive_id=archive_id, requester_id=requester_id, first_claimer_id=first_claimer_id, channel_id=interaction.channel.id)
                try:
                    await interaction.response.send_modal(modal2)
                except Exception:
                    await interaction.response.send_message("Failed to open approval modal.", ephemeral=True)
                return

            # Handle approve/deny close actions
            if cid and isinstance(cid, str) and (cid.startswith("ticket_close_approve:") or cid.startswith("ticket_close_deny:")):
                parts = cid.split(":")
                action = parts[0]
                try:
                    archive_id = int(parts[1])
                    requester_id = int(parts[2])
                except Exception:
                    archive_id = None
                    requester_id = None

                arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                details_local = None
                if archive_id and arch_ch:
                    try:
                        msg = await arch_ch.fetch_message(archive_id)
                        details_local = _extract_json_from_codeblock(msg.content or "")
                    except Exception:
                        details_local = None
                if not details_local and isinstance(interaction.channel, discord.TextChannel):
                    details_local = await find_ticket_archive_by_channel(interaction.channel)

                if not details_local:
                    await interaction.response.send_message("Ticket archive not found.", ephemeral=True)
                    return

                claimers = details_local.get("claimers", []) or []
                if not claimers:
                    await interaction.response.send_message("No claimer available to approve.", ephemeral=True)
                    return

                first_claimer_id = claimers[0]
                if interaction.user.id != first_claimer_id:
                    await interaction.response.send_message("Only the original claimer can approve or deny close requests.", ephemeral=True)
                    return

                pending = details_local.get("pending_close_request")
                if not pending:
                    await interaction.response.send_message("No pending close request found.", ephemeral=True)
                    return

                if action == "ticket_close_approve":
                    reason_value = pending.get("reason", "No reason provided")
                    requester_member = interaction.channel.guild.get_member(requester_id) or None
                    details_local["status"] = "closed"
                    details_local["close_reason"] = reason_value
                    details_local["closed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                    details_local["closed_by"] = f"{requester_member} ({requester_id})" if requester_member else f"{requester_id}"
                    details_local.pop("pending_close_request", None)
                    if archive_id:
                        await edit_archive_message(archive_id, details_local)

                    # Lock and delete channel
                    try:
                        ch = interaction.channel
                        await ch.set_permissions(ch.guild.default_role, view_channel=True, send_messages=False)
                        owner_role = ch.guild.get_role(TICKET_TYPES.get(details_local.get("ticket_type"), {}).get("owner_role_id"))
                        if owner_role:
                            await ch.set_permissions(owner_role, view_channel=True, send_messages=False)
                        for rid in STAFF_ROLES:
                            r = ch.guild.get_role(rid)
                            if r:
                                await ch.set_permissions(r, view_channel=True, send_messages=False)
                        if ch.name.endswith("-open"):
                            await ch.edit(name=ch.name.replace("-open", "-closed"))
                        else:
                            if not ch.name.endswith("-closed"):
                                await ch.edit(name=f"{ch.name}-closed")
                    except Exception:
                        pass

                    try:
                        logs_ch = await ensure_channel(TICKET_LOGS_CHANNEL_ID)
                        if logs_ch:
                            embed = discord.Embed(title=f"Ticket Closed — {interaction.channel.name}", color=discord.Color.red())
                            embed.add_field(name="Ticket", value=interaction.channel.mention, inline=False)
                            embed.add_field(name="Type", value=details_local.get("ticket_type", "N/A"), inline=True)
                            embed.add_field(name="Opened By", value=details_local.get("opener", "N/A"), inline=True)
                            embed.add_field(name="Closed At", value=details_local.get("closed_at", "N/A"), inline=True)
                            embed.add_field(name="Closed By", value=details_local.get("closed_by", "N/A"), inline=True)
                            claimers_text = ", ".join([f"<@{c}>" for c in details_local.get("claimers", [])]) or "None"
                            embed.add_field(name="Claimers", value=claimers_text, inline=False)
                            embed.add_field(name="Close Reason", value=details_local.get("close_reason", "No reason provided"), inline=False)
                            await logs_ch.send(embed=embed)
                    except Exception:
                        pass

                    # delete channel
                    try:
                        await interaction.channel.delete(reason="Ticket closed by approver")
                    except Exception:
                        pass

                    try:
                        await interaction.response.send_message("Approved and ticket closed.", ephemeral=True)
                    except Exception:
                        pass
                    return
                else:
                    details_local.pop("pending_close_request", None)
                    if archive_id:
                        await edit_archive_message(archive_id, details_local)
                    try:
                        await interaction.channel.send(embed=discord.Embed(description=f"{interaction.user.mention} denied the close request.", color=discord.Color.orange()))
                    except Exception:
                        pass
                    try:
                        await interaction.response.send_message("Denied the close request.", ephemeral=True)
                    except Exception:
                        pass
                    return

            # IA claim handling (allow claims for IA cases)
            if cid and isinstance(cid, str) and cid.startswith("ia_claim:"):
                try:
                    chan = interaction.channel
                    if not isinstance(chan, discord.TextChannel):
                        await interaction.response.send_message("Claim can only be used inside case channels.", ephemeral=True)
                        return
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
                        if archive_id:
                            try:
                                await edit_archive_message(archive_id, details)
                            except Exception:
                                pass

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

            # Expand button handling
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

                details = None
                try:
                    content = archive_msg.content or ""
                    parsed = _extract_json_from_codeblock(content)
                    details = parsed
                except Exception:
                    details = None

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

                try:
                    detail_embed = discord.Embed(title="Detailed Log Information", color=discord.Color.dark_blue())
                    ts = details.get("timestamp")
                    if ts:
                        detail_embed.set_footer(text=f"Logged at {ts}")

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

                return

        # Slash command logging
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
        logger.exception("on_interaction error")


# ====== Slash command: Anti-Ping (user-facing) =======
class PublicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="antiping", description="Click here to manage or turn on anti ping")
    async def antiping(self, interaction: discord.Interaction):
        if not interaction.user:
            try:
                await interaction.response.send_message("User context unavailable.", ephemeral=True)
            except Exception:
                pass
            return
        try:
            modal = AntiPingModal(requester=interaction.user)
            await interaction.response.send_modal(modal)
        except Exception:
            try:
                await interaction.response.send_message("Failed to open Anti-Ping setup.", ephemeral=True)
            except Exception:
                pass


# ====== BOT EVENTS & startup =======
startup_import_task = None


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")

    # load existing antiping records into memory
    try:
        await _load_antiping_from_archive()
    except Exception:
        logger.exception("Failed to load anti-ping entries on startup")

    # start ticket inactivity loop
    try:
        bot.loop.create_task(ticket_inactivity_loop())
    except Exception:
        logger.exception("Failed to start ticket inactivity loop")

    # register cogs
    try:
        if not bot.get_cog("PublicCommands"):
            res = bot.add_cog(PublicCommands(bot))
            if inspect.isawaitable(res):
                await res
    except Exception:
        logger.exception("Failed to add PublicCommands cog")

    try:
        if not bot.get_cog("AutoResponder"):
            res = bot.add_cog(AutoResponder(bot))
            if inspect.isawaitable(res):
                await res
    except Exception:
        logger.exception("Failed to add AutoResponder cog")

    # ensure ticket UI exists
    try:
        await ensure_ticket_ui_messages()
    except Exception:
        logger.exception("Failed to ensure ticket UI messages")

    # sync app commands to guild so /antiping appears
    try:
        guild_obj = discord.Object(id=MAIN_GUILD_ID)
        try:
            bot.tree.copy_global_to(guild=guild_obj)
        except Exception:
            pass
        sync_res = bot.tree.sync(guild=guild_obj)
        if inspect.isawaitable(sync_res):
            await sync_res
        logger.info("App commands synced to guild.")
    except Exception:
        logger.exception("Failed to sync app commands on_ready")

    # startup import (infractions) safe task
    global startup_import_task
    if startup_import_task is None:
        async def _startup_import():
            try:
                logger.info("Starting limited startup infraction import (safe).")
                try:
                    res = await scan_and_archive_infractions(limit=300)
                    if res.get("available"):
                        logger.info(f"Startup import finished: {res}")
                    else:
                        logger.info("Startup import skipped: channels not available.")
                except Exception:
                    pass
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
            pass
    except Exception:
        pass
    try:
        await guild.leave()
    except Exception:
        pass


# ====== Run =======
bot.run(TOKEN)
