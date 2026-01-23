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
import aiosqlite

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

# Configuration constants
BATCH_SIZE = 200
BATCH_SLEEP = 0.25
SCAN_INTERVAL_SECONDS = 300
INACTIVITY_THRESHOLD_HOURS = 6
INACTIVITY_REPEAT_HOURS = 24
MAX_ANTIPING_HOURS = 720  # 30 days max

# Database file
DB_FILE = "bot_data.db"

# ====== Logging setup =======
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("discord_bot")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ------------------------
# Database initialization
# ------------------------
async def init_database():
    """Initialize SQLite database for persistent storage"""
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            # Infractions table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS infractions (
                    code TEXT PRIMARY KEY,
                    message_id INTEGER UNIQUE,
                    user TEXT,
                    user_id INTEGER,
                    punishment TEXT,
                    reason TEXT,
                    issued_by TEXT,
                    expires TEXT,
                    timestamp TEXT,
                    attachments TEXT,
                    extra TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Anti-ping table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS antiping (
                    user_id INTEGER PRIMARY KEY,
                    archive_msg_id INTEGER,
                    status TEXT,
                    started_at TEXT,
                    duration_hours REAL,
                    expires_at TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Tickets table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    channel_id INTEGER PRIMARY KEY,
                    archive_msg_id INTEGER,
                    ticket_type TEXT,
                    channel_name TEXT,
                    opener_id INTEGER,
                    opened_by_id INTEGER,
                    status TEXT,
                    claimers TEXT,
                    close_reason TEXT,
                    closed_by TEXT,
                    inactivity_pinged_at TEXT,
                    created_at TEXT,
                    closed_at TEXT
                )
            """)
            
            # Scan state table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scan_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_scanned_at TEXT,
                    archive_msg_id INTEGER
                )
            """)
            
            await db.commit()
            logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)


# ------------------------
# Global state for improved infraction scanning
# ------------------------
known_infraction_codes: Set[str] = set()
known_infraction_msgids: Set[int] = set()

# scan state stored in database
_scan_state_archive_id: Optional[int] = None
_last_scan_dt: Optional[datetime] = None

# Anti-ping in-memory map + helpers
anti_ping_map: Dict[int, Dict[str, Any]] = {}
ANTIPING_ARCHIVE_TYPE = "antiping"


def _antiping_is_expired(entry: Dict[str, Any]) -> bool:
    """Check if anti-ping entry has expired"""
    exp = entry.get("expires_at")
    if not exp:
        return False
    try:
        exp_dt = datetime.fromisoformat(exp)
        return datetime.now(timezone.utc) >= exp_dt
    except Exception as e:
        logger.error(f"Error checking anti-ping expiry: {e}")
        return False


def validate_duration(duration_str: str) -> Optional[float]:
    """Validate and parse duration string"""
    if not duration_str:
        return None
    try:
        hours = float(duration_str.strip())
        if 0 < hours <= MAX_ANTIPING_HOURS:
            return hours
        logger.warning(f"Duration {hours} outside valid range")
    except ValueError as e:
        logger.error(f"Invalid duration format: {duration_str} - {e}")
    return None


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
    """Check if user has staff role"""
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    return any(role.id in STAFF_ROLES for role in user.roles)


def is_bod(interaction: discord.Interaction) -> bool:
    """Check if user has BoD role"""
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    return any(role.id == BOD_ROLE_ID for role in user.roles)


def is_ia(interaction: discord.Interaction) -> bool:
    """Check if user has IA role"""
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    return any(role.id == IA_ROLE_ID for role in user.roles)


async def ensure_channel(channel_id: int) -> Optional[discord.TextChannel]:
    """Get or fetch a channel by ID"""
    ch = bot.get_channel(channel_id)
    if ch:
        return ch
    try:
        ch = await bot.fetch_channel(channel_id)
        return ch
    except Exception as e:
        logger.error(f"Failed to fetch channel {channel_id}: {e}")
        return None


def _extract_json_from_codeblock(content: str) -> Optional[Dict[str, Any]]:
    """Extract JSON from Discord code block"""
    if not content:
        return None
    content = content.strip()
    
    # Remove code block markers
    if content.startswith("```") and content.endswith("```"):
        lines = content.splitlines()
        if len(lines) >= 3:
            inner = "\n".join(lines[1:-1])
        else:
            inner = ""
    else:
        inner = content
    
    # Try direct parse
    try:
        return json.loads(inner)
    except json.JSONDecodeError:
        pass
    
    # Try regex extraction
    m = re.search(r"\{.*\}", inner, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
    
    return None


async def archive_details_to_mod_channel(details: Dict[str, Any]) -> Optional[int]:
    """Archive details to mod channel and return message ID"""
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
        except Exception as e:
            logger.error(f"Failed to load ticket UI state: {e}", exc_info=True)

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
       )
    if not archive_ch:
        logger.error("Archive channel not available")
        return None
    
    try:
        details_serializable = json.dumps(details, default=str, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to serialize details: {e}")
        details_serializable = json.dumps({k: str(v) for k, v in details.items()}, ensure_ascii=False, indent=2)
    
    archive_content = f"```json\n{details_serializable}\n```"
    try:
        msg = await archive_ch.send(content=archive_content)
        return msg.id
    except Exception as e:
        logger.error(f"Failed to send archive message: {e}", exc_info=True)
        return None


async def edit_archive_message(archive_msg_id: int, details: Dict[str, Any]) -> bool:
    """Edit an existing archive message"""
    archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not archive_ch:
        return False
    
    try:
        archive_msg = await archive_ch.fetch_message(archive_msg_id)
    except Exception as e:
        logger.error(f"Failed to fetch archive message {archive_msg_id}: {e}")
        return False
    
    try:
        content = json.dumps(details, default=str, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to serialize details: {e}")
        content = json.dumps({k: str(v) for k, v in details.items()}, ensure_ascii=False, indent=2)
    
    try:
        await archive_msg.edit(content=f"```json\n{content}\n```")
        return True
    except Exception as e:
        logger.error(f"Failed to edit archive message: {e}", exc_info=True)
        return False


async def send_embed_with_expand(channel: discord.TextChannel, embed: discord.Embed, details: Dict[str, Any]) -> Optional[discord.Message]:
    """Send embed with expand button and archive details"""
    archive_msg_id = None
    
    # Archive certain event types
    if details.get("event_type") in ["infract", "slash_command", "ticket", "antiping"]:
        try:
            archive_msg_id = await archive_details_to_mod_channel(details)
        except Exception as e:
            logger.error(f"Failed to archive details: {e}", exc_info=True)
    
    view = ExpandView(archive_msg_id) if archive_msg_id else None
    
    try:
        msg = await channel.send(embed=embed, view=view)
        return msg
    except discord.HTTPException as e:
        if e.status == 429:
            logger.warning(f"Rate limited, retrying after {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            try:
                msg = await channel.send(embed=embed, view=view)
                return msg
            except Exception as retry_e:
                logger.error(f"Failed to send after retry: {retry_e}", exc_info=True)
        else:
            logger.error(f"Failed to send embed: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error sending embed: {e}", exc_info=True)
    
    return None


# ------------------------
# Database helpers for infraction index
# ------------------------
async def load_infraction_index_from_db():
    """Load infraction index from database"""
    global known_infraction_codes, known_infraction_msgids
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("SELECT code, message_id FROM infractions") as cursor:
                async for row in cursor:
                    if row[0]:
                        known_infraction_codes.add(str(row[0]))
                    if row[1]:
                        known_infraction_msgids.add(int(row[1]))
        logger.info(f"Loaded {len(known_infraction_codes)} infractions from database")
    except Exception as e:
        logger.error(f"Failed to load infraction index from database: {e}", exc_info=True)


async def save_infraction_to_db(details: Dict[str, Any]):
    """Save infraction to database"""
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("""
                INSERT OR REPLACE INTO infractions 
                (code, message_id, user, user_id, punishment, reason, issued_by, expires, timestamp, attachments, extra)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                details.get("code"),
                details.get("infraction_message_id"),
                details.get("user"),
                details.get("user_id"),
                details.get("punishment"),
                details.get("reason"),
                details.get("issued_by"),
                details.get("expires"),
                details.get("timestamp"),
                json.dumps(details.get("attachments", [])),
                json.dumps(details.get("extra")) if details.get("extra") else None
            ))
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to save infraction to database: {e}", exc_info=True)


async def load_scan_state():
    """Load last scan datetime from database"""
    global _scan_state_archive_id, _last_scan_dt
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("SELECT last_scanned_at, archive_msg_id FROM scan_state WHERE id = 1") as cursor:
                row = await cursor.fetchone()
                if row:
                    try:
                        _last_scan_dt = datetime.fromisoformat(row[0]) if row[0] else None
                        _scan_state_archive_id = row[1]
                        logger.info(f"Loaded scan state: last_scanned_at={_last_scan_dt}")
                    except Exception as e:
                        logger.error(f"Error parsing scan state: {e}")
    except Exception as e:
        logger.error(f"Failed to load scan state: {e}", exc_info=True)


async def save_scan_state(dt: datetime):
    """Save scan state to database"""
    global _scan_state_archive_id
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("""
                INSERT OR REPLACE INTO scan_state (id, last_scanned_at, archive_msg_id)
                VALUES (1, ?, ?)
            """, (dt.isoformat(), _scan_state_archive_id))
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to save scan state: {e}", exc_info=True)


# ------------------------
# Load anti-ping state from database
# ------------------------
async def load_antiping_state():
    """Load active anti-ping entries from database"""
    global anti_ping_map
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("""
                SELECT user_id, archive_msg_id, status, started_at, duration_hours, expires_at
                FROM antiping WHERE status = 'active'
            """) as cursor:
                async for row in cursor:
                    user_id = row[0]
                    anti_ping_map[user_id] = {
                        "archive_msg_id": row[1],
                        "status": row[2],
                        "started_at": row[3],
                        "duration_hours": row[4],
                        "expires_at": row[5]
                    }
        logger.info(f"Loaded {len(anti_ping_map)} active anti-ping entries")
    except Exception as e:
        logger.error(f"Failed to load anti-ping state: {e}", exc_info=True)


async def save_antiping_to_db(user_id: int, entry: Dict[str, Any]):
    """Save anti-ping entry to database"""
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("""
                INSERT OR REPLACE INTO antiping 
                (user_id, archive_msg_id, status, started_at, duration_hours, expires_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                user_id,
                entry.get("archive_msg_id"),
                entry.get("status"),
                entry.get("started_at"),
                entry.get("duration_hours"),
                entry.get("expires_at")
            ))
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to save anti-ping to database: {e}", exc_info=True)


# ------------------------
# Batched incremental infraction scanner
# ------------------------
async def scan_batch(limit: int = BATCH_SIZE) -> Dict[str, int]:
    """Scan infraction channel for new messages"""
    global _last_scan_dt
    infra_ch = await ensure_channel(INFRACTION_CHANNEL_ID)
    if not infra_ch:
        logger.error("Infraction channel not available")
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
    except Exception as e:
        logger.error(f"Failed to fetch infractions history: {e}", exc_info=True)
        return {"scanned": 0, "archived": 0, "skipped": 0, "errors": 1}

    newest_processed_dt: Optional[datetime] = None

    for msg in msgs_to_process:
        scanned += 1
        try:
            created_at = msg.created_at.replace(tzinfo=timezone.utc) if msg.created_at.tzinfo is None else msg.created_at.astimezone(timezone.utc)
            if newest_processed_dt is None or created_at > newest_processed_dt:
                newest_processed_dt = created_at
        except Exception as e:
            logger.error(f"Error processing message timestamp: {e}")

        parsed_infraction = None

        # Try to parse embed first
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
                    except Exception as field_e:
                        logger.error(f"Error parsing embed fields: {field_e}")
                    
                    parsed_infraction = {
                        "code": code_val,
                        "user": fields.get("user", ""),
                        "punishment": fields.get("punishment", ""),
                        "reason": fields.get("reason", ""),
                        "issued_by": fields.get("issued by", "") or fields.get("issued_by", ""),
                        "expires": fields.get("expires", ""),
                        "timestamp": created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                        "infraction_message_id": msg.id,
                        "event_type": "infract",
                        "attachments": [a.url for a in msg.attachments] if msg.attachments else [],
                        "extra": None,
                    }
                    break

        # Fallback parse raw content
        if not parsed_infraction:
            content = msg.content or ""
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
                    "timestamp": created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "infraction_message_id": msg.id,
                    "event_type": "infract",
                    "attachments": [a.url for a in msg.attachments] if msg.attachments else [],
                    "extra": {"raw_content": content[:2000]},
                }

        if not parsed_infraction:
            skipped += 1
            continue

        # Duplicate check
        duplicate = False
        code_to_check = parsed_infraction.get("code")
        if code_to_check and str(code_to_check) in known_infraction_codes:
            duplicate = True
        if parsed_infraction.get("infraction_message_id") and int(parsed_infraction.get("infraction_message_id")) in known_infraction_msgids:
            duplicate = True

        if duplicate:
            skipped += 1
            continue

        # Prepare details
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
            "extra": parsed_infraction.get("extra"),
        }

        try:
            # Save to database
            await save_infraction_to_db(details)
            
            # Log to channel
            log_ch = await ensure_channel(LOGGING_CHANNEL_ID)
            if log_ch:
                log_embed = discord.Embed(title="(Imported) Staff Infraction", color=discord.Color.red())
                log_embed.add_field(name="Code", value=str(details.get("code") or "N/A"), inline=True)
                log_embed.add_field(name="Punishment", value=details.get("punishment") or "N/A", inline=True)
                log_embed.add_field(name="Issued By", value=details.get("issued_by") or "Unknown", inline=True)
                log_embed.set_footer(text=f"At {details.get('timestamp')}")
                await send_embed_with_expand(log_ch, log_embed, details)
            
            # Update known sets
            if details.get("code"):
                known_infraction_codes.add(str(details.get("code")))
            if details.get("infraction_message_id"):
                known_infraction_msgids.add(int(details.get("infraction_message_id")))
            
            archived += 1
            await asyncio.sleep(BATCH_SLEEP)
        except Exception as e:
            logger.error(f"Failed to process infraction: {e}", exc_info=True)
            errors += 1
            await asyncio.sleep(BATCH_SLEEP)

    # Save scan state
    if newest_processed_dt:
        try:
            _last_scan_dt = newest_processed_dt
            await save_scan_state(newest_processed_dt)
        except Exception as e:
            logger.error(f"Failed to save scan state: {e}", exc_info=True)

    return {"scanned": scanned, "archived": archived, "skipped": skipped, "errors": errors}


async def infra_scan_loop():
    """Background loop for scanning infractions"""
    await bot.wait_until_ready()
    
    # Initial load
    await load_infraction_index_from_db()
    await load_scan_state()
    
    # Initial batch
    try:
        result = await scan_batch(limit=100)
        logger.info(f"Initial infraction scan: {result}")
    except Exception as e:
        logger.error(f"Initial scan_batch failed: {e}", exc_info=True)
    
    while not bot.is_closed():
        try:
            res = await scan_batch(limit=BATCH_SIZE)
            logger.debug(f"Infraction scan batch result: {res}")
        except Exception as e:
            logger.error(f"infra_scan_loop error: {e}", exc_info=True)
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


# ------------------------
# Anti-ping persistence helpers
# ------------------------
async def _save_antiping_entry(parsed: Dict[str, Any]) -> Optional[int]:
    """Save anti-ping entry to archive and database"""
    archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID)
    if not archive_ch:
        return None
    
    try:
        content = json.dumps(parsed, default=str, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to serialize anti-ping: {e}")
        content = json.dumps({k: str(v) for k, v in parsed.items()}, ensure_ascii=False, indent=2)
    
    payload = f"```json\n{content}\n```"
    
    try:
        aid = parsed.get("_archive_msg_id")
        if aid:
            try:
                msg = await archive_ch.fetch_message(int(aid))
                await msg.edit(content=payload)
                return msg.id
            except Exception as e:
                logger.error(f"Failed to edit archive message: {e}")
        
        newm = await archive_ch.send(content=payload)
        return newm.id
    except Exception as e:
        logger.error(f"Failed to save antiping archive entry: {e}", exc_info=True)
        return None


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
    """Sanitize display name for use as channel name"""
    name = display_name.lower().replace(" ", "-")
    name = re.sub(r"[^a-z0-9\-]", "", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    if not name:
        name = "user"
    return name[:80]


async def ensure_ticket_ui_messages():
    """Ensure ticket UI messages exist in support channel"""
    support_ch = await ensure_channel(SUPPORT_CHANNEL_ID)
    if not support_ch:
        logger.warning("Support channel not available for ticket UI creation.")
        return

    archive_ch = await ensure_channel(MOD_ARCHIVE_CHANNEL_ID
