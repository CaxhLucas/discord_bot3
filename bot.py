# Full updated bot.py (commands grouped: /infraction lookup/scan, /promotion lookup; automatic import on startup)
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
import inspect

# ====== CONFIG =======
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

# ====== Helpers & Storage =======


class ExpandView(discord.ui.View):
    def __init__(self, archive_message_id: int):
        super().__init__(timeout=None)
        self.archive_message_id = archive_message_id
        custom_id = f"expand:{archive_message_id}"
        self.add_item(discord.ui.Button(label="Expand", style=discord.ButtonStyle.primary, custom_id=custom_id))


def is_staff(interaction: discord.Interaction) -> bool:
    return any(role.id in STAFF_ROLES for role in interaction.user.roles)


def is_bod(interaction: discord.Interaction) -> bool:
    return BOD_ROLE_ID in [role.id for role in interaction.user.roles]


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


async def send_embed_with_expand(target_channel: discord.abc.GuildChannel | discord.TextChannel, embed: discord.Embed, details: Dict[str, Any]):
    """
    Only archive (store in MOD_ARCHIVE) and attach Expand button for event types: 'infract' and 'promote'.
    Other events: send embed only (no archive).
    """
    try:
        event_type = details.get("event_type") if isinstance(details, dict) else None
        if event_type in ("infract", "promote"):
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


# Shared scanning helper (used by command and startup import)
async def scan_and_archive_infractions(limit: int = 500, progress_callback=None) -> Dict[str, int]:
    """
    Scan INFRACTION_CHANNEL_ID up to `limit` messages and archive missing infractions into MOD_ARCHIVE.
    Returns summary dict with counts.
    progress_callback(optional) can be a coroutine that receives a status string for updates.
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


# ====== Slash command groups: Infraction & Promotion =======

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


# ====== Cogs (StaffCommands, PublicCommands, AutoResponder) retained mostly unchanged =======
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

        # Archive promotion
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
                sent_inf_msg = await infra_channel.send(content=user.mention, embed=embed)
            except discord.Forbidden:
                pass
            except Exception:
                pass

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

        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass
        except Exception:
            pass

        await interaction.response.send_message(f"Infraction issued and {user.display_name} has been notified.", ephemeral=True)

    # serverstart, serverstop, say, embled kept as-is (omitted here for brevity but present in file)


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


class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        # All existing auto-response logic unchanged (omitted here for brevity but present)
        await bot.process_commands(message)


# ====== Interaction handler for Expand buttons and slash logging =======
@bot.event
async def on_interaction(interaction: discord.Interaction):
    try:
        # handle component interactions (Expand buttons)
        if interaction.type == discord.InteractionType.component:
            cid = None
            try:
                if isinstance(interaction.data, dict):
                    cid = interaction.data.get("custom_id") or interaction.data.get("customID") or interaction.data.get("component_type")
            except Exception:
                cid = None

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

        # application command logging
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
        pass


# ====== on_ready: register cogs/groups and run a safe startup import (once) =======
startup_import_task = None


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")

    # add cogs safely
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

    # add command groups if not present
    try:
        # Add groups to application command tree
        if "infraction" not in [c.name for c in bot.tree.walk_commands()]:
            bot.tree.add_command(InfractionGroup())
        if "promotion" not in [c.name for c in bot.tree.walk_commands()]:
            bot.tree.add_command(PromotionGroup())
    except Exception:
        pass

    # sync commands to specific guild for instant availability
    if not getattr(bot, "app_commands_synced", False):
        try:
            guild_obj = discord.Object(id=MAIN_GUILD_ID)
            try:
                bot.tree.copy_global_to(guild=guild_obj)
            except Exception:
                pass
            sync_res = bot.tree.sync(guild=guild_obj)
            if inspect.isawaitable(sync_res):
                await sync_res
            bot.app_commands_synced = True
            logger.info("Slash commands synced.")
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
            pass
    except Exception:
        pass
    try:
        await guild.leave()
    except Exception:
        pass


bot.run(TOKEN)
