import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import asyncio
from datetime import datetime, timezone, timedelta
import random
import logging
from typing import Any, Dict, Optional, List, Set
import json
import re
import inspect

# Compatibility: Check if ButtonStyle.success exists, otherwise use primary
SUCCESS_BUTTON_STYLE = getattr(discord.ButtonStyle, "success", discord.ButtonStyle.primary)

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
IA_CATEGORY_ID = 1452383883336351794

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
# Global state for improved infraction scanning
# ------------------------
known_infraction_codes: Set[str] = set()
known_infraction_msgids: Set[int] = set()

# scan state stored in MOD_ARCHIVE: event_type "infraction_scan_state"
_scan_state_archive_id: Optional[int] = None
_last_scan_dt: Optional[datetime] = None

# ------------------------
# Anti-ping in-memory map + helpers
# ------------------------
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

def is_bod_or_ia(interaction: discord.Interaction) -> bool:
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    return any(role.id == BOD_ROLE_ID or role.id == IA_ROLE_ID for role in user.roles)

def is_bod(interaction: discord.Interaction) -> bool:
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    return any(role.id == BOD_ROLE_ID for role in user.roles)

def is_supervisor_or_bod(interaction: discord.Interaction) -> bool:
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    return any(role.id in [BOD_ROLE_ID] + SUPERVISOR_ROLE_IDS for role in user.roles)

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
        if event_type in ("infract", "promote", "ia_case"):
            archive_msg_id = await archive_details_to_mod_channel(details)
            archive_id = archive_msg_id or 0
            view = ExpandView(archive_id)
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
    except Exception:
        pass

# ------------------------
# Infraction index & scan-state
# ------------------------
async def load_infraction_index(lookback: int = 5000):
    global known_infraction_codes, known_infraction_msgids
    arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not arch_ch:
        return
    try:
        async for m in arch_ch.history(limit=lookback):
            parsed = _extract_json_from_codeblock(m.content or "")
            if not parsed:
                continue
            if parsed.get("event_type") == "infract":
                code = parsed.get("code")
                if code:
                    known_infraction_codes.add(str(code))
                mid = parsed.get("infraction_message_id")
                if mid:
                    try:
                        known_infraction_msgids.add(int(mid))
                    except Exception:
                        pass
    except Exception:
        logger.exception("Failed to build infraction index")

async def load_scan_state():
    global _scan_state_archive_id, _last_scan_dt
    arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not arch_ch:
        return
    try:
        async for m in arch_ch.history(limit=1000):
            parsed = _extract_json_from_codeblock(m.content or "")
            if parsed and parsed.get("event_type") == "infraction_scan_state":
                try:
                    last = parsed.get("last_scanned_at")
                    if last:
                        _last_scan_dt = datetime.fromisoformat(last)
                except Exception:
                    _last_scan_dt = None
                _scan_state_archive_id = m.id
                break
    except Exception:
        logger.exception("Failed to load scan state")

async def save_scan_state(dt: datetime):
    global _scan_state_archive_id
    entry = {"event_type": "infraction_scan_state", "last_scanned_at": dt.isoformat()}
    try:
        if _scan_state_archive_id:
            await edit_archive_message(_scan_state_archive_id, entry)
        else:
            aid = await archive_details_to_mod_channel(entry)
            if aid:
                _scan_state_archive_id = aid
    except Exception:
        logger.exception("Failed to save scan state")

# ------------------------
# Batched incremental infraction scanner
# ------------------------
BATCH_SIZE = 200
BATCH_SLEEP = 0.25
SCAN_INTERVAL_SECONDS = 300

async def scan_batch(limit: int = BATCH_SIZE) -> Dict[str, int]:
    global _last_scan_dt
    infra_ch = await ensure_channel(INFRACTION_CHANNEL_ID)
    if not infra_ch:
        return {"scanned": 0, "archived": 0, "skipped": 0, "errors": 0}
    scanned = archived = skipped = errors = 0
    msgs_to_process: List[discord.Message] = []

    try:
        if _last_scan_dt:
            async for m in infra_ch.history(limit=limit, after=_last_scan_dt, oldest_first=True):
                msgs_to_process.append(m)
        else:
            async for m in infra_ch.history(limit=limit, oldest_first=True):
                msgs_to_process.append(m)
    except Exception:
        logger.exception("Failed to fetch infractions history")
        return {"scanned": 0, "archived": 0, "skipped": 0, "errors": 1}

    newest_processed_dt: Optional[datetime] = None

    for msg in msgs_to_process:
        scanned += 1
        try:
            created_at = msg.created_at.replace(tzinfo=timezone.utc) if msg.created_at.tzinfo is None else msg.created_at.astimezone(timezone.utc)
            if newest_processed_dt is None or created_at > newest_processed_dt:
                newest_processed_dt = created_at
        except Exception:
            pass

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
                        "timestamp": created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if created_at else "",
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
                    "timestamp": created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if created_at else "",
                    "infraction_message_id": msg.id,
                    "event_type": "infract",
                    "attachments": [a.url for a in msg.attachments] if msg.attachments else [],
                    "extra": {"raw_content": content[:2000]},
                }

        if not parsed_infraction:
            skipped += 1
            continue

        duplicate = False
        code_to_check = parsed_infraction.get("code")
        if code_to_check and str(code_to_check) in known_infraction_codes:
            duplicate = True
        if parsed_infraction.get("infraction_message_id") and int(parsed_infraction.get("infraction_message_id")) in known_infraction_msgids:
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
            if details.get("code"):
                known_infraction_codes.add(str(details.get("code")))
            if details.get("infraction_message_id"):
                try:
                    known_infraction_msgids.add(int(details.get("infraction_message_id")))
                except Exception:
                    pass
            archived += 1
            await asyncio.sleep(BATCH_SLEEP)
        except Exception:
            errors += 1
            await asyncio.sleep(BATCH_SLEEP)
            continue

    if newest_processed_dt:
        try:
            _last_scan_dt = newest_processed_dt
            await save_scan_state(newest_processed_dt)
        except Exception:
            logger.exception("Failed to save scan state")

    return {"scanned": scanned, "archived": archived, "skipped": skipped, "errors": errors}

async def infra_scan_loop():
    await bot.wait_until_ready()
    await load_infraction_index(lookback=5000)
    await load_scan_state()
    try:
        await scan_batch(limit=100)
    except Exception:
        logger.exception("Initial scan_batch failed")
    while not bot.is_closed():
        try:
            res = await scan_batch(limit=BATCH_SIZE)
            logger.debug(f"Infraction scan batch result: {res}")
        except Exception:
            logger.exception("infra_scan_loop error")
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)

# ------------------------
# Anti-ping persistence helpers
# ------------------------
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
# Ticket system
# ------------------------
TICKET_TYPES = {
    "partnership": {
        "title": "Partnership Ticket",
        "description": "Click on the button below to open an Partnership ticket!",
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
    channel_name = f"{sanitized}-{ticket_type}"

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
    role_ping_text = f"<@&{role_ping}>" if role_ping else ""
    initial_embed = discord.Embed(title=conf["title"], description=f"{role_ping_text}\n\nHello! Thank you for contacting the Iowa State Roleplay Support Team. Please state the reason for opening the ticket, and a support member will respond when they're available!", color=discord.Color.green())
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
        "main_claimer": None,
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

async def collect_ticket_history(channel: discord.TextChannel) -> str:
    """Collect full message history from ticket channel"""
    history_lines = []
    try:
        async for msg in channel.history(limit=None, oldest_first=True):
            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            author = f"{msg.author.display_name} ({msg.author.id})"
            content = msg.content or "[No text content]"
            
            history_lines.append(f"[{timestamp}] {author}: {content}")
            
            if msg.embeds:
                for idx, embed in enumerate(msg.embeds):
                    history_lines.append(f"  └─ Embed {idx+1}: {embed.title or 'No title'} - {embed.description or 'No description'}")
            
            if msg.attachments:
                for att in msg.attachments:
                    history_lines.append(f"  └─ Attachment: {att.url}")
    except Exception as e:
        logger.exception("Failed to collect ticket history")
        history_lines.append(f"[ERROR] Failed to collect complete history: {e}")
    
    return "\n".join(history_lines)

# ------------------------
# Modals
# ------------------------
class AntiPingModal(discord.ui.Modal, title="Anti-Ping — Duration (optional)"):
    duration = discord.ui.TextInput(label="Duration (hours, blank = indefinite)", required=False, max_length=20, placeholder="e.g. 6 or 24")

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
        # Use success style (with fallback for compatibility)
        view.add_item(discord.ui.Button(label="Start/Resume", style=SUCCESS_BUTTON_STYLE, custom_id=custom_prefix + ":start"))

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
        
        # Collect full message history
        full_history = await collect_ticket_history(chan)
        
        details["status"] = "closed"
        details["close_reason"] = reason_text
        details["closed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        details["message_history"] = full_history
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
                
                # Add note about full summary in archive
                archive_note = f"Full ticket summary with message history saved to archive (ID: {archive_id})" if archive_id else "Full summary saved to archive"
                embed.set_footer(text=archive_note)
                
                await logs_ch.send(embed=embed)
        except Exception:
            pass

        # Generate comprehensive summary
        try:
            logs_ch = await ensure_channel(TICKET_LOGS_CHANNEL_ID)
            if logs_ch:
                # Create comprehensive summary embed
                summary_embed = discord.Embed(
                    title=f"📋 Ticket Summary — {details.get('ticket_type', 'Unknown').upper()}",
                    color=discord.Color.blue()
                )
                
                # Basic Info
                summary_embed.add_field(name="Ticket Type", value=details.get("ticket_type", "N/A").title(), inline=True)
                summary_embed.add_field(name="Channel", value=f"{chan.name} ({chan.id})", inline=True)
                summary_embed.add_field(name="Status", value="Closed", inline=True)
                
                # Opener Info
                summary_embed.add_field(name="Opened By", value=details.get("opener", "N/A"), inline=True)
                summary_embed.add_field(name="Opened At", value=details.get("created_at", "N/A"), inline=True)
                
                # Closer Info
                summary_embed.add_field(name="Closed By", value=details.get("closed_by", "N/A"), inline=True)
                summary_embed.add_field(name="Closed At", value=details.get("closed_at", "N/A"), inline=True)
                summary_embed.add_field(name="Close Reason", value=details.get("close_reason", "No reason provided"), inline=False)
                
                # Claimers
                claimers = details.get("claimers", []) or []
                main_claimer = details.get("main_claimer")
                if claimers:
                    claimer_mentions = []
                    for cid in claimers:
                        try:
                            member = chan.guild.get_member(cid)
                            if member:
                                claimer_mentions.append(f"{member.mention} ({'Main' if cid == main_claimer else 'Secondary'})")
                            else:
                                claimer_mentions.append(f"<@{cid}> ({'Main' if cid == main_claimer else 'Secondary'})")
                        except Exception:
                            claimer_mentions.append(f"<@{cid}> ({'Main' if cid == main_claimer else 'Secondary'})")
                    summary_embed.add_field(name="Claimers", value="\n".join(claimer_mentions) if claimer_mentions else "None", inline=False)
                else:
                    summary_embed.add_field(name="Claimers", value="None", inline=False)
                
                # Message Count
                try:
                    msg_count = len([m async for m in chan.history(limit=None)])
                    summary_embed.add_field(name="Total Messages", value=str(msg_count), inline=True)
                except Exception:
                    summary_embed.add_field(name="Total Messages", value="Unknown", inline=True)
                
                # Duration
                try:
                    opened_dt = datetime.fromisoformat(details.get("created_at", "").replace(" UTC", "+00:00"))
                    closed_dt = datetime.fromisoformat(details.get("closed_at", "").replace(" UTC", "+00:00"))
                    duration = closed_dt - opened_dt
                    hours = int(duration.total_seconds() / 3600)
                    minutes = int((duration.total_seconds() % 3600) / 60)
                    summary_embed.add_field(name="Duration", value=f"{hours}h {minutes}m", inline=True)
                except Exception:
                    summary_embed.add_field(name="Duration", value="Unknown", inline=True)
                
                # Inactivity Info
                inactivity_pinged = details.get("inactivity_pinged_at")
                if inactivity_pinged:
                    summary_embed.add_field(name="Inactivity Warning", value=f"Sent at {inactivity_pinged}", inline=False)
                
                # Archive reference
                if archive_id:
                    summary_embed.add_field(name="Archive ID", value=str(archive_id), inline=True)
                    summary_embed.add_field(name="Full History", value=f"Complete message history saved to archive", inline=False)
                
                summary_embed.set_footer(text=f"Ticket ID: {archive_id or 'N/A'}")
                
                await logs_ch.send(embed=summary_embed)
        except Exception:
            logger.exception("Failed to send ticket summary to logs")

        try:
            await interaction.response.send_message("Ticket closed. Channel will be deleted.", ephemeral=True)
        except Exception:
            pass

        # Delete channel immediately after closing
        try:
            await asyncio.sleep(2)  # Small delay to ensure message is sent
            await chan.delete(reason="Ticket closed")
        except Exception:
            logger.exception(f"Failed to delete ticket channel {chan.id}")

class ClaimApprovalView(discord.ui.View):
    """View for main claimer to approve additional claimers"""
    def __init__(self, requester_id: int, channel_id: int, archive_id: Optional[int]):
        super().__init__(timeout=300)  # 5 minute timeout
        self.requester_id = requester_id
        self.channel_id = channel_id
        self.archive_id = archive_id
    
    @discord.ui.button(label="Approve", style=SUCCESS_BUTTON_STYLE)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Load ticket details
        details = None
        if self.archive_id:
            arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
            if arch_ch:
                try:
                    am = await arch_ch.fetch_message(self.archive_id)
                    details = _extract_json_from_codeblock(am.content or "")
                except Exception:
                    pass
        
        if details:
            claimers = details.get("claimers", []) or []
            if self.requester_id not in claimers:
                claimers.append(self.requester_id)
                details["claimers"] = claimers
                if self.archive_id:
                    await edit_archive_message(self.archive_id, details)
        
        try:
            await interaction.response.send_message(f"<@{self.requester_id}> has been approved and added as a claimer.", ephemeral=False)
        except Exception:
            pass
        
        # Disable buttons
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
    
    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.send_message(f"Claim request from <@{self.requester_id}> was denied.", ephemeral=False)
        except Exception:
            pass
        
        # Disable buttons
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

class CloseApprovalView(discord.ui.View):
    """View for main claimer to approve closing ticket"""
    def __init__(self, requester_id: int, channel_id: int, archive_id: Optional[int], main_claimer_id: int):
        super().__init__(timeout=300)  # 5 minute timeout
        self.requester_id = requester_id
        self.channel_id = channel_id
        self.archive_id = archive_id
        self.main_claimer_id = main_claimer_id
    
    @discord.ui.button(label="Yes", style=SUCCESS_BUTTON_STYLE)
    async def approve_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only main claimer can approve
        if interaction.user.id != self.main_claimer_id:
            try:
                await interaction.response.send_message("Only the main claimer can approve this request.", ephemeral=True)
            except Exception:
                pass
            return
        
        try:
            await interaction.response.send_message(f"Close request from <@{self.requester_id}> approved. They can now close the ticket.", ephemeral=False)
        except Exception:
            pass
        
        # Store approval in archive so requester can close
        if self.archive_id:
            arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
            if arch_ch:
                try:
                    am = await arch_ch.fetch_message(self.archive_id)
                    details = _extract_json_from_codeblock(am.content or "")
                    if details:
                        approved_closers = details.get("approved_closers", []) or []
                        if self.requester_id not in approved_closers:
                            approved_closers.append(self.requester_id)
                            details["approved_closers"] = approved_closers
                            await edit_archive_message(self.archive_id, details)
                except Exception:
                    pass
        
        # Notify requester
        chan = bot.get_channel(self.channel_id)
        if isinstance(chan, discord.TextChannel):
            try:
                await chan.send(f"<@{self.requester_id}> Your close request was approved by the main claimer. You can now click the Close button to provide a reason and close the ticket.")
            except Exception:
                pass
        
        # Disable buttons
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
    
    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def deny_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only main claimer can deny
        if interaction.user.id != self.main_claimer_id:
            try:
                await interaction.response.send_message("Only the main claimer can deny this request.", ephemeral=True)
            except Exception:
                pass
            return
        
        try:
            await interaction.response.send_message(f"Close request from <@{self.requester_id}> was denied.", ephemeral=False)
        except Exception:
            pass
        
        # Disable buttons
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

class InactivityActionView(discord.ui.View):
    """View for staff to decide on inactive tickets"""
    def __init__(self, channel_id: int, archive_id: Optional[int]):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        self.archive_id = archive_id
    
    @discord.ui.button(label="Keep Open", style=SUCCESS_BUTTON_STYLE, custom_id="inactivity_keep")
    async def keep_open(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user is a claimer
        details = None
        if self.archive_id:
            arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
            if arch_ch:
                try:
                    am = await arch_ch.fetch_message(self.archive_id)
                    details = _extract_json_from_codeblock(am.content or "")
                except Exception:
                    pass
        
        if details:
            claimers = details.get("claimers", []) or []
            if interaction.user.id not in claimers and not any(r.id in STAFF_ROLES for r in getattr(interaction.user, "roles", [])):
                try:
                    await interaction.response.send_message("Only claimers can control this ticket.", ephemeral=True)
                except Exception:
                    pass
                return
            
            # Reset inactivity timer
            details["inactivity_pinged_at"] = None
            if self.archive_id:
                await edit_archive_message(self.archive_id, details)
        
        try:
            await interaction.response.send_message("Ticket will remain open.", ephemeral=False)
        except Exception:
            pass
        
        # Delete the inactivity message
        try:
            await interaction.message.delete()
        except Exception:
            pass
    
    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="inactivity_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user is a claimer
        details = None
        if self.archive_id:
            arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
            if arch_ch:
                try:
                    am = await arch_ch.fetch_message(self.archive_id)
                    details = _extract_json_from_codeblock(am.content or "")
                except Exception:
                    pass
        
        if details:
            claimers = details.get("claimers", []) or []
            if interaction.user.id not in claimers and not any(r.id in STAFF_ROLES for r in getattr(interaction.user, "roles", [])):
                try:
                    await interaction.response.send_message("Only claimers can control this ticket.", ephemeral=True)
                except Exception:
                    pass
                return
        
        # Show close reason modal
        modal = CloseReasonModal(self.archive_id, interaction.user.id, self.channel_id)
        try:
            await interaction.response.send_modal(modal)
        except Exception:
            pass

# ------------------------
# Ticket inactivity checking
# ------------------------
INACTIVITY_THRESHOLD_HOURS = 24
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
            
            # First warning at 24 hours
            if hours_idle >= INACTIVITY_THRESHOLD_HOURS and not inactivity_pinged_at:
                mention_text = f"<@{opener_id}>" if opener_id else ""
                try:
                    if mention_text:
                        await chan.send(content=mention_text)
                    embed = discord.Embed(
                        title="⚠️ Ticket Inactivity",
                        description="This ticket will be automatically reviewed within 24 hours of inactivity.",
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
            
            # Second action at 48 hours total (24 hours after first ping)
            elif inactivity_pinged_at and (now - inactivity_pinged_at).total_seconds() >= INACTIVITY_REPEAT_HOURS * 3600:
                claimers = parsed.get("claimers", []) or []
                claimer_mentions = " ".join([f"<@{c}>" for c in claimers]) if claimers else ""
                
                try:
                    if claimer_mentions:
                        await chan.send(content=claimer_mentions)
                    
                    embed = discord.Embed(
                        title="⚠️ Ticket Inactivity - Action Required",
                        description="This ticket has been inactive for 48 hours. Please choose an action:",
                        color=discord.Color.red()
                    )
                    view = InactivityActionView(channel_id, archive_msg_id)
                    await chan.send(embed=embed, view=view)
                    
                    # Reset the ping time so it doesn't spam
                    parsed["inactivity_pinged_at"] = now.isoformat()
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
        await asyncio.sleep(1800)  # Check every 30 minutes

# ------------------------
# Slash command groups
# ------------------------
class InfractionGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="infraction", description="Infraction commands (BOD only)")

    @app_commands.command(name="lookup", description="Lookup prior infractions for a staff member (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(staff="Staff member to lookup")
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
            embed.set_footer(text=f"Showing 10 most recent of {len(found)} infractions.")
        else:
            embed.set_footer(text="Use Expand on archive messages for full details.")

        await interaction.followup.send(embed=embed, ephemeral=False)

    @app_commands.command(name="scan", description="Scan old infractions channel and archive missing entries (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(limit="How many messages to scan (max 2000)")
    async def scan(self, interaction: discord.Interaction, limit: int = 1000):
        await interaction.response.defer(ephemeral=True)
        if limit <= 0:
            limit = 1000
        if limit > 2000:
            limit = 2000

        result = await scan_batch(limit=limit)
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
            embed.set_footer(text=f"Showing 10 most recent of {len(found)} promotions.")

        await interaction.followup.send(embed=embed, ephemeral=False)

class IAGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="ia", description="Internal Affairs commands (IA only)")

    @app_commands.command(name="open", description="Open an I.A. Case")
    @app_commands.check(is_ia)
    @app_commands.describe(
        investigated="Member being investigated",
        reason="Reason for opening this case",
        details="Additional description (optional)",
        include_agents="Include I.A. Agents",
        include_supervisors="Include I.A. Supervisors",
        include_bod="Include Board of Directors",
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

        case_str = f"{case_num:06d}"

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Guild context unavailable.", ephemeral=True)
            return

        category = discord.utils.get(guild.categories, id=IA_CATEGORY_ID)
        channel_name = f"ia-case-{case_str}-open"

        overwrites: Dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {}
        everyone_role = guild.default_role
        overwrites[everyone_role] = discord.PermissionOverwrite(view_channel=False)

        ia_role = guild.get_role(IA_ROLE_ID)
        if ia_role:
            overwrites[ia_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        allowed_role_ids = []
        allowed_member_ids = []

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

        if include_owners:
            try:
                owner = await guild.fetch_member(guild.owner_id)
                overwrites[owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                allowed_member_ids.append(owner.id)
            except Exception:
                pass

        try:
            overwrites[investigated] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            allowed_member_ids.append(investigated.id)
        except Exception:
            pass

        try:
            opener_member = interaction.user
            overwrites[opener_member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            allowed_member_ids.append(opener_member.id)
        except Exception:
            pass

        me = guild.me or guild.get_member(bot.user.id)
        if me:
            overwrites[me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True, read_message_history=True, manage_channels=True)

        try:
            chan = await guild.create_text_channel(channel_name, category=category, overwrites=overwrites, reason=f"IA case opened by {interaction.user}")
        except Exception as e:
            await interaction.followup.send(f"Failed to create case channel: {e}", ephemeral=True)
            return

        case_embed = discord.Embed(title=f"Case {case_str}", color=discord.Color.red())
        case_embed.add_field(name="Investigating", value=f"{investigated.mention}", inline=False)
        case_embed.add_field(name="For", value=reason, inline=False)
        case_embed.add_field(name="Investigator", value=f"{interaction.user.mention}", inline=False)

        note_text = (
            f"Note: DO NOT DM ANYONE about this case. Any information about this case must be put here or in evidence "
            f"<#{EVIDENCE_CHANNEL_ID}>. If you are the one being investigated, or you have any involvement; DO NOT LEAVE "
            "THE SERVER. If you do and rejoin, you WILL be staff-blacklisted. After the case is closed "
            "DO NOT delete this channel so we have a record of this case."
        )
        case_embed.add_field(name="Important", value=note_text, inline=False)
        case_embed.add_field(name="Close", value='To close this case, please type `-close`', inline=False)

        try:
            sent = await chan.send(content=f"<@&{IA_ROLE_ID}> {investigated.mention}", embed=case_embed)
            try:
                await sent.pin(reason="Pin IA case initial embed")
            except Exception:
                pass
        except Exception:
            sent = None

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
            "claimers": [],
            "status": "open",
            "created_at": created_at,
            "closed_at": None,
            "closed_by": None,
        }
        archive_msg_id = None
        if await ensure_channel(MOD_ARCHIVE_CHANNEL_ID):
            archive_msg_id = await archive_details_to_mod_channel(archive_details)
        try:
            topic = f"ia_archive:{archive_msg_id or 0} case:{case_str}"
            await chan.edit(topic=topic)
        except Exception:
            pass

        await interaction.followup.send(f"Opened IA case {case_str} in {chan.mention}", ephemeral=False)

# ------------------------
# Public Commands Cog
# ------------------------
class PublicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="antiping", description="Manage or turn on anti ping")
    async def antiping(self, interaction: discord.Interaction):
        if not interaction.user:
            try:
                await interaction.response.send_message("User context unavailable.", ephemeral=True)
            except Exception:
                pass
            return
        
        # Ensure user is a Member (not a User) for guild commands
        if not isinstance(interaction.user, discord.Member):
            try:
                await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            except Exception:
                pass
            return
        
        try:
            modal = AntiPingModal(requester=interaction.user)
            await interaction.response.send_modal(modal)
        except Exception as e:
            logger.exception("Failed to open antiping modal")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"Failed to open Anti-Ping setup: {str(e)}", ephemeral=True)
                else:
                    await interaction.followup.send(f"Failed to open Anti-Ping setup: {str(e)}", ephemeral=True)
            except Exception as e2:
                logger.exception("Failed to send error message for antiping command")

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
                f"• Next, send over your server ad so I can post it in <#{PARTNERSHIP_CHANNEL_ID}>.\n"
                "• Then, please wait for further instructions from our support member!"
            ),
            color=discord.Color.blue()
        )
        embed.set_image(url=SUPPORT_EMBED_BANNER)
        await interaction.response.send_message(embed=embed, ephemeral=False)

# ------------------------
# Auto Responder Cog
# ------------------------
class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        
        # Anti-ping enforcement
        try:
            if isinstance(message.channel, discord.TextChannel):
                mentioned_ids = [m.id for m in message.mentions]
                if mentioned_ids:
                    for target_id in mentioned_ids:
                        entry = anti_ping_map.get(int(target_id))
                        if entry:
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
                                pass
                            return
        except Exception:
            logger.exception("Anti-ping enforcement error")

        content = message.content.strip().lower()

        # IA close/reopen handling
        try:
            ch = message.channel
            if isinstance(ch, discord.TextChannel) and ch.category_id == IA_CATEGORY_ID:
                if content.startswith("-close"):
                    member = message.author
                    if not any(r.id == IA_ROLE_ID for r in member.roles):
                        try:
                            await message.channel.send("You do not have permission to close this case.", delete_after=8)
                        except Exception:
                            pass
                        return

                    topic = ch.topic or ""
                    match = re.search(r"ia_archive:(\d+)", topic)
                    archive_id = int(match.group(1)) if match else None

                    details = None
                    if archive_id:
                        archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                        if archive_ch:
                            try:
                                archive_msg = await archive_ch.fetch_message(archive_id)
                                details = _extract_json_from_codeblock(archive_msg.content or "")
                            except Exception:
                                pass

                    if not details:
                        archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                        if archive_ch:
                            try:
                                async for m in archive_ch.history(limit=2000):
                                    p = _extract_json_from_codeblock(m.content or "")
                                    if p and p.get("event_type") == "ia_case" and p.get("channel_id") == ch.id:
                                        details = p
                                        archive_id = m.id
                                        break
                            except Exception:
                                pass

                    if not details:
                        details = {"event_type": "ia_case", "claimers": [], "allowed_role_ids": [], "allowed_member_ids": []}

                    claimers = details.get("claimers", []) or []
                    if member.id not in claimers:
                        claimers.append(member.id)
                    details["claimers"] = claimers
                    details["status"] = "closed"
                    details["closed_by"] = f"{member} ({member.id})"
                    details["closed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

                    if archive_id:
                        try:
                            await edit_archive_message(archive_id, details)
                        except Exception:
                            pass

                    try:
                        await ch.set_permissions(ch.guild.default_role, view_channel=True, send_messages=False)
                    except Exception:
                        pass

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

                    try:
                        if ch.name.endswith("-open"):
                            await ch.edit(name=ch.name.replace("-open", "-closed"))
                        else:
                            if "-closed" not in ch.name:
                                await ch.edit(name=f"{ch.name}-closed")
                    except Exception:
                        pass

                    offenders_text = details.get("investigated", "Unknown")
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

                if content.startswith("-reopen"):
                    member = message.author
                    if not any(r.id == IA_ROLE_ID for r in member.roles):
                        try:
                            await message.channel.send("You do not have permission to reopen this case.", delete_after=8)
                        except Exception:
                            pass
                        return

                    topic = ch.topic or ""
                    match = re.search(r"ia_archive:(\d+)", topic)
                    archive_id = int(match.group(1)) if match else None

                    details = None
                    if archive_id:
                        archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                        if archive_ch:
                            try:
                                archive_msg = await archive_ch.fetch_message(archive_id)
                                details = _extract_json_from_codeblock(archive_msg.content or "")
                            except Exception:
                                pass

                    if not details:
                        archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                        if archive_ch:
                            try:
                                async for m in archive_ch.history(limit=2000):
                                    p = _extract_json_from_codeblock(m.content or "")
                                    if p and p.get("event_type") == "ia_case" and p.get("channel_id") == ch.id:
                                        details = p
                                        archive_id = m.id
                                        break
                            except Exception:
                                pass

                    if not details:
                        details = {"allowed_role_ids": [], "allowed_member_ids": []}

                    details["status"] = "open"
                    details["closed_by"] = None
                    details["closed_at"] = None
                    if archive_id:
                        try:
                            await edit_archive_message(archive_id, details)
                        except Exception:
                            pass

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

                    try:
                        if ch.name.endswith("-closed"):
                            await ch.edit(name=ch.name.replace("-closed", "-open"))
                        else:
                            if "-open" not in ch.name:
                                await ch.edit(name=f"{ch.name}-open")
                    except Exception:
                        pass

                    try:
                        await ch.send(f"This case has been reopened by {member.mention}")
                    except Exception:
                        pass
                    return
        except Exception:
            pass

        # Message-based commands
        if content.startswith("-inactive"):
            # Check if in a ticket channel
            if not isinstance(message.channel, discord.TextChannel):
                return
            if message.channel.category_id != TICKET_CATEGORY_ID:
                return
            
            # Check if user is staff
            if not any(role.id in STAFF_ROLES for role in message.author.roles):
                try:
                    await message.channel.send("Only staff members can use this command.", delete_after=8)
                except Exception:
                    pass
                return
            
            try:
                await message.delete()
            except Exception:
                pass
            
            # Get ticket details
            topic = message.channel.topic or ""
            match = re.search(r"ticket_archive:(\d+)", topic)
            archive_id = int(match.group(1)) if match else None
            
            details = None
            if archive_id:
                arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                if arch_ch:
                    try:
                        am = await arch_ch.fetch_message(archive_id)
                        details = _extract_json_from_codeblock(am.content or "")
                    except Exception:
                        pass
            
            if not details:
                arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                if arch_ch:
                    try:
                        async for m in arch_ch.history(limit=2000):
                            p = _extract_json_from_codeblock(m.content or "")
                            if p and p.get("event_type") == TICKET_ARCHIVE_TYPE and p.get("channel_id") == message.channel.id:
                                details = p
                                archive_id = m.id
                                break
                    except Exception:
                        pass
            
            if not details:
                try:
                    await message.channel.send("Ticket details not found.", delete_after=8)
                except Exception:
                    pass
                return
            
            opener_id = details.get("opener_id")
            main_claimer = details.get("main_claimer")
            claimers = details.get("claimers", []) or []
            
            # Ping opener with 24-hour warning
            opener_mention = f"<@{opener_id}>" if opener_id else ""
            embed = discord.Embed(
                title="⚠️ Ticket Inactivity Warning",
                description=f"{opener_mention} This ticket has been marked as inactive.\n\n**This ticket will be automatically closed in 24 hours if no response is received.**\n\nPlease respond to keep this ticket open.",
                color=discord.Color.orange()
            )
            embed.set_footer(text="24-hour countdown started")
            
            try:
                warning_msg = await message.channel.send(content=opener_mention if opener_id else None, embed=embed)
            except Exception:
                warning_msg = None
            
            # Update archive with inactivity ping time
            details["inactivity_pinged_at"] = datetime.now(timezone.utc).isoformat()
            details["inactivity_warning_msg_id"] = warning_msg.id if warning_msg else None
            if archive_id:
                try:
                    await edit_archive_message(archive_id, details)
                except Exception:
                    pass
            
            # Schedule 24-hour follow-up
            async def inactivity_followup():
                await asyncio.sleep(24 * 60 * 60)  # 24 hours
                
                # Re-check ticket status
                arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                if arch_ch and archive_id:
                    try:
                        am = await arch_ch.fetch_message(archive_id)
                        updated_details = _extract_json_from_codeblock(am.content or "")
                        if updated_details and updated_details.get("status") == "open":
                            # Still open, ping main claimer with panel
                            chan = bot.get_channel(message.channel.id)
                            if isinstance(chan, discord.TextChannel):
                                main_claimer_id = updated_details.get("main_claimer")
                                if main_claimer_id:
                                    claimer_mention = f"<@{main_claimer_id}>"
                                    followup_embed = discord.Embed(
                                        title="⏰ Ticket Inactivity - 24 Hours Elapsed",
                                        description=f"{claimer_mention} This ticket has been inactive for 24 hours after the warning was sent.\n\nPlease decide whether to keep this ticket open or close it.",
                                        color=discord.Color.red()
                                    )
                                    view = InactivityActionView(message.channel.id, archive_id)
                                    try:
                                        await chan.send(content=claimer_mention, embed=followup_embed, view=view)
                                    except Exception:
                                        pass
                    except Exception:
                        logger.exception("Failed to send inactivity follow-up")
            
            asyncio.create_task(inactivity_followup())

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
                description=f"Open a ticket in <#{SUPPORT_CHANNEL_ID}>.",
                color=discord.Color.blurple()
            )
            try:
                await message.channel.send(embed=embed)
            except Exception:
                pass

        elif content == "-partnerinfo":
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
                    f"• Send your server ad so it can be posted in <#{PARTNERSHIP_CHANNEL_ID}>\n"
                    "• Wait for further instructions from a support member"
                ),
                color=discord.Color.blue()
            )
            embed.set_image(url=SUPPORT_EMBED_BANNER)
            try:
                await message.channel.send(embed=embed)
            except Exception:
                pass

        # Partnership command via reply
        if message.reference and "-partnership" in content and any(role.id in STAFF_ROLES for role in message.author.roles):
            try:
                replied_msg = await message.channel.fetch_message(message.reference.message_id)
                partner_channel = bot.get_channel(PARTNERSHIP_CHANNEL_ID)
                if not partner_channel:
                    return

                rep_member = None
                try:
                    if isinstance(replied_msg.author, discord.Member):
                        rep_member = replied_msg.author
                    else:
                        rep_member = message.guild.get_member(replied_msg.author.id)
                except Exception:
                    pass

                is_duplicate = False
                try:
                    async for m in partner_channel.history(limit=500):
                        if rep_member and (str(rep_member.id) in m.content or rep_member.mention in m.content):
                            is_duplicate = True
                            break
                except Exception:
                    pass

                if is_duplicate:
                    return

                msg_content = (
                    f"Staff Member: {message.author.mention}\n"
                    f"Representative: {replied_msg.author.mention}\n"
                    f"Content:\n{replied_msg.content}"
                )

                try:
                    await partner_channel.send(msg_content)
                except Exception:
                    pass

                try:
                    partner_role = message.guild.get_role(1392729143375822898)
                    if partner_role and rep_member:
                        await rep_member.add_roles(partner_role, reason=f"Assigned partnership role by {message.author}")
                except Exception:
                    pass
            except Exception:
                pass

        # Command logging
        try:
            log_ch = bot.get_channel(LOGGING_CHANNEL_ID)
            if log_ch:
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

                if message.content.startswith("/") or message.content.startswith("-"):
                    embed = discord.Embed(title="Message Command Used", color=discord.Color.blue())
                    embed.add_field(name="User", value=f"{message.author}", inline=True)
                    embed.add_field(name="Message", value=message.content[:100], inline=True)
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
            pass

        await bot.process_commands(message)

# ------------------------
# Server warnings & events
# ------------------------
JOIN_THRESHOLD = 3
JOIN_INTERVAL = 60
NEW_ACCOUNT_DAYS = 30
recent_joins = []

@bot.event
async def on_member_join(member):
    now = datetime.now(timezone.utc)
    recent_joins.append((member.id, now))

    try:
        account_age_days = (now - member.created_at.replace(tzinfo=timezone.utc)).days
    except Exception:
        account_age_days = 999

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
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "extra": {"account_age_days": account_age_days},
            }
            await send_embed_with_expand(channel, embed, details)

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
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "extra": {"recent_joins": [r[0] for r in recent_joins_filtered]},
            }
            await send_embed_with_expand(channel, embed, details)

@bot.event
async def on_guild_channel_create(channel):
    try:
        if isinstance(channel, discord.TextChannel) and channel.category_id == TICKET_CATEGORY_ID:
            return

        warn_ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)
        if warn_ch:
            embed = discord.Embed(
                title="🔔 Channel Created",
                description=f"Channel {getattr(channel, 'mention', getattr(channel, 'name', str(channel)))} was created.",
                color=discord.Color.orange()
            )
            details = {
                "event_type": "channel_created",
                "channel": getattr(channel, "name", None),
                "channel_id": getattr(channel, "id", None),
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
            await send_embed_with_expand(warn_ch, embed, details)
    except Exception:
        pass

@bot.event
async def on_guild_channel_delete(channel):
    try:
        warn_ch = bot.get_channel(BOD_ALERT_CHANNEL_ID)
        if warn_ch:
            embed = discord.Embed(
                title="🗑️ Channel Deleted",
                description=f"Channel `{getattr(channel, 'name', 'unknown')}` was deleted.",
                color=discord.Color.orange()
            )
            details = {
                "event_type": "channel_deleted",
                "channel": getattr(channel, "name", None),
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
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
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "extra": {"role_id": role.id, "role_name": role.name},
            }
            await send_embed_with_expand(warn_ch, embed, details)
    except Exception:
        pass

# ------------------------
# Interaction handling
# ------------------------
@bot.event
async def on_interaction(interaction: discord.Interaction):
    try:
        if interaction.type == discord.InteractionType.component:
            cid = None
            try:
                if isinstance(interaction.data, dict):
                    cid = interaction.data.get("custom_id")
            except Exception:
                cid = None

            # Antiping control buttons
            if cid and isinstance(cid, str) and cid.startswith("antiping:"):
                parts = cid.split(":")
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

                allowed = False
                try:
                    if interaction.user.id == owner_id:
                        allowed = True
                    else:
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

                parsed = None
                arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                if archive_id and arch_ch:
                    try:
                        am = await arch_ch.fetch_message(archive_id)
                        parsed = _extract_json_from_codeblock(am.content or "")
                    except Exception:
                        parsed = None

                if not parsed:
                    try:
                        await interaction.response.send_message("Anti-Ping record not found.", ephemeral=True)
                    except Exception:
                        pass
                    return

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

            # Ticket create button
            if cid and cid.startswith("ticket_create:"):
                ticket_type = cid.split(":", 1)[1]
                if ticket_type not in TICKET_TYPES:
                    try:
                        await interaction.response.send_message("Invalid ticket type.", ephemeral=True)
                    except Exception:
                        pass
                    return
                
                user = interaction.user
                opener = interaction.user
                chan, archive_id = await create_ticket_channel_for(user, ticket_type, opener)
                if chan:
                    try:
                        await interaction.response.send_message(f"Ticket created: {chan.mention}", ephemeral=True)
                    except Exception:
                        pass
                else:
                    try:
                        await interaction.response.send_message("Failed to create ticket.", ephemeral=True)
                    except Exception:
                        pass
                return

            # Ticket claim button
            if cid and cid.startswith("ticket_claim:"):
                try:
                    channel_id = int(cid.split(":", 1)[1])
                except Exception:
                    return
                
                chan = bot.get_channel(channel_id)
                if not isinstance(chan, discord.TextChannel):
                    return
                
                topic = chan.topic or ""
                match = re.search(r"ticket_archive:(\d+)", topic)
                archive_id = int(match.group(1)) if match else None
                
                details = None
                if archive_id:
                    arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                    if arch_ch:
                        try:
                            am = await arch_ch.fetch_message(archive_id)
                            details = _extract_json_from_codeblock(am.content or "")
                        except Exception:
                            pass
                
                if not details:
                    # Fallback search
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
                
                if details:
                    claimers = details.get("claimers", []) or []
                    main_claimer = details.get("main_claimer")
                    
                    # If no one has claimed yet, this person becomes the main claimer
                    if not claimers:
                        claimers.append(interaction.user.id)
                        details["claimers"] = claimers
                        details["main_claimer"] = interaction.user.id
                        if archive_id:
                            await edit_archive_message(archive_id, details)
                        
                        try:
                            await interaction.response.send_message(f"{interaction.user.mention} has claimed this ticket as the main claimer.", ephemeral=False)
                        except Exception:
                            pass
                    
                    # If already claimed, request approval from main claimer
                    elif interaction.user.id not in claimers:
                        # Send approval request to main claimer
                        try:
                            view = ClaimApprovalView(interaction.user.id, chan.id, archive_id)
                            await chan.send(
                                content=f"<@{main_claimer}> {interaction.user.mention} wants to claim this ticket. Do you approve?",
                                view=view
                            )
                            await interaction.response.send_message("Claim request sent to the main claimer.", ephemeral=True)
                        except Exception:
                            pass
                    else:
                        try:
                            await interaction.response.send_message("You have already claimed this ticket.", ephemeral=True)
                        except Exception:
                            pass
                return

            # Ticket close button
            if cid and cid.startswith("ticket_close:"):
                try:
                    channel_id = int(cid.split(":", 1)[1])
                except Exception:
                    return
                
                chan = bot.get_channel(channel_id)
                if not isinstance(chan, discord.TextChannel):
                    return
                
                topic = chan.topic or "" if chan else ""
                match = re.search(r"ticket_archive:(\d+)", topic)
                archive_id = int(match.group(1)) if match else None
                
                # Get ticket details
                details = None
                if archive_id:
                    arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                    if arch_ch:
                        try:
                            am = await arch_ch.fetch_message(archive_id)
                            details = _extract_json_from_codeblock(am.content or "")
                        except Exception:
                            pass
                
                if not details:
                    # Fallback search
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
                
                if not details:
                    try:
                        await interaction.response.send_message("Ticket details not found.", ephemeral=True)
                    except Exception:
                        pass
                    return
                
                # Get ticket info
                ticket_type = details.get("ticket_type", "")
                owner_role_id = TICKET_TYPES.get(ticket_type, {}).get("owner_role_id")
                claimers = details.get("claimers", []) or []
                main_claimer = details.get("main_claimer")
                is_claimer = interaction.user.id in claimers
                is_main_claimer = interaction.user.id == main_claimer
                
                # Check if user has owner role
                has_owner_role = False
                if isinstance(interaction.user, discord.Member) and owner_role_id:
                    owner_role = chan.guild.get_role(owner_role_id)
                    if owner_role and owner_role in interaction.user.roles:
                        has_owner_role = True
                
                # If unclaimed, anyone can close
                if not claimers:
                    modal = CloseReasonModal(archive_id, interaction.user.id, channel_id)
                    try:
                        await interaction.response.send_modal(modal)
                    except Exception:
                        pass
                    return
                
                # If claimed:
                # - Only owner role can close directly
                # - If non-owner tries to close, request approval from main claimer
                if has_owner_role:
                    # Owner role can close directly
                    modal = CloseReasonModal(archive_id, interaction.user.id, channel_id)
                    try:
                        await interaction.response.send_modal(modal)
                    except Exception:
                        pass
                    return
                else:
                    # Non-owner trying to close claimed ticket - need main claimer approval
                    if main_claimer:
                        # Check if already approved
                        approved_closers = details.get("approved_closers", []) or []
                        if interaction.user.id in approved_closers:
                            # Already approved, allow close
                            modal = CloseReasonModal(archive_id, interaction.user.id, channel_id)
                            try:
                                await interaction.response.send_modal(modal)
                            except Exception:
                                pass
                            return
                        
                        # Send approval request
                        view = CloseApprovalView(interaction.user.id, channel_id, archive_id, main_claimer)
                        try:
                            await chan.send(
                                content=f"<@{main_claimer}> {interaction.user.mention} wants to close this ticket. Do you approve?",
                                view=view
                            )
                            await interaction.response.send_message("Close request sent to the main claimer for approval.", ephemeral=True)
                        except Exception:
                            try:
                                await interaction.response.send_message("Failed to send approval request.", ephemeral=True)
                            except Exception:
                                pass
                    else:
                        try:
                            await interaction.response.send_message("Only the ticket owner role can close this ticket.", ephemeral=True)
                        except Exception:
                            pass
                    return

            # Expand button
            if cid and cid.startswith("expand:"):
                try:
                    archive_id = int(cid.split(":", 1)[1])
                except Exception:
                    try:
                        await interaction.response.send_message("Details not available.", ephemeral=True)
                    except Exception:
                        pass
                    return

                arch_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
                if not arch_ch:
                    try:
                        await interaction.response.send_message("Archive channel not available.", ephemeral=True)
                    except Exception:
                        pass
                    return

                try:
                    archive_msg = await arch_ch.fetch_message(archive_id)
                except Exception:
                    try:
                        await interaction.response.send_message("Archive message not found.", ephemeral=True)
                    except Exception:
                        pass
                    return

                details = _extract_json_from_codeblock(archive_msg.content or "")
                if not details:
                    try:
                        await interaction.response.send_message("Could not parse details.", ephemeral=True)
                    except Exception:
                        pass
                    return

                detail_embed = discord.Embed(title="Detailed Information", color=discord.Color.dark_blue())
                for key in ["event_type", "user", "code", "punishment", "reason", "issued_by", "timestamp"]:
                    if key in details and details.get(key):
                        value = str(details.get(key))
                        if len(value) > 1024:
                            value = value[:1020] + "..."
                        detail_embed.add_field(name=key.replace("_", " ").title(), value=value, inline=False)

                try:
                    await interaction.response.send_message(embed=detail_embed, ephemeral=True)
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
                pass
            
            try:
                ch = bot.get_channel(LOGGING_CHANNEL_ID)
                if ch:
                    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                    embed = discord.Embed(title="Slash Command Used", color=discord.Color.blue())
                    embed.add_field(name="User", value=f"{interaction.user}", inline=True)
                    embed.add_field(name="Command", value=f"/{cmd_name}", inline=True)
                    channel_info = getattr(interaction.channel, "mention", "DM") if interaction.channel else "DM"
                    embed.add_field(name="Channel", value=channel_info, inline=True)
                    embed.set_footer(text=f"At {now_str}")

                    details = {
                        "event_type": "slash_command",
                        "user": f"{interaction.user} ({interaction.user.id})",
                        "user_id": interaction.user.id,
                        "command": f"/{cmd_name}",
                        "timestamp": now_str,
                    }
                    await send_embed_with_expand(ch, embed, details)
            except Exception:
                pass
    except Exception:
        logger.exception("on_interaction error")

# ------------------------
# Bot ready & startup
# ------------------------
startup_import_task = None

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")

    # Load infraction index and scan state
    try:
        await load_infraction_index(lookback=5000)
        await load_scan_state()
    except Exception:
        logger.exception("Failed to initialize infraction index/state")

    # Start background loops
    try:
        bot.loop.create_task(infra_scan_loop())
    except Exception:
        logger.exception("Failed to start infra_scan_loop")

    try:
        bot.loop.create_task(ticket_inactivity_loop())
    except Exception:
        logger.exception("Failed to start ticket inactivity loop")

    # Register cogs
    try:
        if not bot.get_cog("PublicCommands"):
            res = bot.add_cog(PublicCommands(bot))
            if inspect.isawaitable(res):
                await res
            logger.info("PublicCommands cog added successfully")
            # Log registered commands for debugging
            commands_list = [cmd.name for cmd in bot.tree.walk_commands() if hasattr(cmd, 'name')]
            logger.info(f"Registered app commands: {commands_list}")
    except Exception:
        logger.exception("Failed to add PublicCommands cog")

    try:
        if not bot.get_cog("StaffCommands"):
            res = bot.add_cog(StaffCommands(bot))
            if inspect.isawaitable(res):
                await res
    except Exception:
        logger.exception("Failed to add StaffCommands cog")

    try:
        if not bot.get_cog("AutoResponder"):
            res = bot.add_cog(AutoResponder(bot))
            if inspect.isawaitable(res):
                await res
    except Exception:
        logger.exception("Failed to add AutoResponder cog")

    # Add command groups
    try:
        existing = [c.name for c in bot.tree.walk_commands()]
        if "infraction" not in existing:
            bot.tree.add_command(InfractionGroup())
        if "promotion" not in existing:
            bot.tree.add_command(PromotionGroup())
        if "ia" not in existing:
            bot.tree.add_command(IAGroup())
    except Exception:
        logger.exception("Failed to add command groups")

    # Ensure ticket UI exists
    try:
        await ensure_ticket_ui_messages()
    except Exception:
        logger.exception("Failed to ensure ticket UI messages")

    # Sync slash commands
    try:
        guild_obj = discord.Object(id=MAIN_GUILD_ID)
        try:
            bot.tree.copy_global_to(guild=guild_obj)
        except Exception:
            pass
        sync_res = bot.tree.sync(guild=guild_obj)
        if inspect.isawaitable(sync_res):
            synced = await sync_res
        else:
            synced = sync_res
        logger.info(f"App commands synced to guild. Synced {len(synced) if synced else 0} commands.")
        # Log synced command names for debugging
        if synced:
            synced_names = [cmd.name if hasattr(cmd, 'name') else str(cmd) for cmd in synced]
            logger.info(f"Synced commands: {synced_names}")
    except Exception:
        logger.exception("Failed to sync app commands on_ready")

    # Startup import
    global startup_import_task
    if startup_import_task is None:
        async def _startup_import():
            try:
                logger.info("Starting limited startup infraction import.")
                try:
                    res = await scan_batch(limit=100)
                    logger.info(f"Startup infraction batch finished: {res}")
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
