import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import datetime
import json
import os
import re
import random
import traceback


# ---- CONFIG ----
TOKEN = os.environ["DISCORD_TOKEN"]


MAIN_GUILD_ID = 1371272556820041849
BOD_ROLE_ID = 1371272557034209493
SUPERVISOR_ROLE_IDS = [1371272557034209491, 1371272557034209496]
OWNER_IDS = [902727710990811186, 1341152829967958114]


PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 1400683360623267870
SESSION_CHANNEL_ID = 1396277983211163668
SSU_ROLE_ID = 1371272556820041854
EVENT_ROLE_ID = 1371272556820041853
ANNOUNCEMENT_ROLE_ID = 1371272556820041852
GIVEAWAY_ROLE_ID = 1400878647753048164
REACTION_CHANNEL_ID = 1371272557969281159
LOGGING_CHANNEL_ID = 1371272557692452884
SUGGESTION_CHANNEL_ID = 1401761820431355986


LEVEL_ROLES = {
    1: 1401750387542855710,
    5: 1401750539229728919,
    10: 1401750605822824478,
    20: 1401750676911947837,
}


XP_DATA_FILE = "xp_data.json"
GIVEAWAYS_DATA_FILE = "giveaways.json"


# ---- INTENTS ----
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True
intents.reactions = True


bot = commands.Bot(command_prefix="!", intents=intents)


# ---- HELPERS ----
def is_staff(interaction: discord.Interaction) -> bool:
    roles = getattr(interaction.user, 'roles', [])
    return any(r.id == BOD_ROLE_ID or r.id in SUPERVISOR_ROLE_IDS for r in roles)


def save_json(filename: str, data: dict):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)


def load_json(filename: str) -> dict:
    if not os.path.exists(filename):
        return {}
    with open(filename, "r") as f:
        return json.load(f)


def parse_duration(duration_str: str) -> int | None:
    duration_str = duration_str.lower().replace(" ", "")
    match = re.match(r"(\d+)([smhd])", duration_str)
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    return {"s": amount, "m": amount*60, "h": amount*3600, "d": amount*86400}.get(unit)


xp_data = load_json(XP_DATA_FILE)
giveaways = load_json(GIVEAWAYS_DATA_FILE)


# ---- LEVELING ----
async def save_xp():
    save_json(XP_DATA_FILE, xp_data)


async def update_level(member: discord.Member, channel: discord.TextChannel):
    user_id = str(member.id)
    xp_data.setdefault(user_id, {"messages": 0, "level": 0})
    xp_data[user_id]["messages"] += 1


    msg_count = xp_data[user_id]["messages"]
    prev_level = xp_data[user_id]["level"]


    if msg_count >= 250:
        new_level = 20
    elif msg_count >= 100:
        new_level = 10
    elif msg_count >= 50:
        new_level = 5
    elif msg_count >= 1:
        new_level = 1
    else:
        new_level = prev_level


    if new_level > prev_level:
        xp_data[user_id]["level"] = new_level
        # Remove old level roles except new_level
        for lvl, role_id in LEVEL_ROLES.items():
            role = member.guild.get_role(role_id)
            if role in member.roles and lvl != new_level:
                try:
                    await member.remove_roles(role)
                except:
                    pass


        # Add new role
        new_role_id = LEVEL_ROLES.get(new_level)
        if new_role_id:
            role = member.guild.get_role(new_role_id)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role)
                except:
                    pass


        # Send level-up message and auto delete after 10 seconds
        try:
            msg = await channel.send(f"🎉 **{member.display_name}** reached **Level {new_level}**!")
            await asyncio.sleep(10)
            await msg.delete()
        except:
            pass


        await save_xp()


# ---- GIVEAWAYS ----
async def save_giveaways():
    save_json(GIVEAWAYS_DATA_FILE, giveaways)


@bot.event
async def on_raw_reaction_add(payload):
    if str(payload.message_id) not in giveaways:
        return
    if str(payload.emoji) != "🎉":
        return
    if payload.user_id == bot.user.id:
        return
    g = giveaways[str(payload.message_id)]
    if payload.user_id not in g["participants"]:
        g["participants"].append(payload.user_id)
        await save_giveaways()


@tasks.loop(seconds=60)
async def giveaway_check():
    now = int(datetime.datetime.utcnow().timestamp())
    to_remove = []
    for gid, g in giveaways.items():
        if g["end_time"] <= now:
            channel = bot.get_channel(g["channel_id"])
            if not channel:
                to_remove.append(gid)
                continue
            try:
                message = await channel.fetch_message(int(gid))
            except:
                to_remove.append(gid)
                continue
            participants = g.get("participants", [])
            if not participants:
                await channel.send(f"Giveaway for **{g['prize']}** ended, no entries.")
            else:
                winners = random.sample(participants, min(g["winners"], len(participants)))
                await channel.send(f"🎉 Giveaway ended! Congrats: {' '.join(f'<@{w}>' for w in winners)} — Prize: **{g['prize']}**!")
            to_remove.append(gid)
    for gid in to_remove:
        giveaways.pop(gid, None)
    if to_remove:
        await save_giveaways()


# ---- COGS ----
class StaffCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="promote")
    @app_commands.check(is_staff)
    async def promote(self, interaction, user: discord.Member, new_rank: str, reason: str):
        e = discord.Embed(title="📈 Staff Promotion", color=discord.Color.green(), timestamp=datetime.datetime.utcnow())
        e.add_field(name="User", value=user.mention)
        e.add_field(name="New Rank", value=new_rank)
        e.add_field(name="Reason", value=reason, inline=False)
        e.add_field(name="By", value=interaction.user.mention)
        await interaction.guild.get_channel(PROMOTION_CHANNEL_ID).send(embed=e)
        await interaction.response.send_message(f"{user.mention} promoted.", ephemeral=True)


    @app_commands.command(name="infract")
    @app_commands.check(is_staff)
    async def infract(self, interaction, user: discord.Member, reason: str, punishment: str, expires: str = "N/A"):
        e = discord.Embed(title="⚠️ Staff Infraction", color=discord.Color.red(), timestamp=datetime.datetime.utcnow())
        e.add_field(name="User", value=user.mention)
        e.add_field(name="Punishment", value=punishment)
        e.add_field(name="Reason", value=reason, inline=False)
        e.add_field(name="By", value=interaction.user.mention)
        e.add_field(name="Expires", value=expires)
        await interaction.guild.get_channel(INFRACTION_CHANNEL_ID).send(embed=e)
        await interaction.response.send_message(f"{user.mention} infracted.", ephemeral=True)


    @app_commands.command(name="serverstart")
    @app_commands.check(is_staff)
    async def serverstart(self, interaction):
        e = discord.Embed(
            title="✅ Session Started",
            description=(
                "The Staff Team has started a session!\n\n"
                "**Server Name:** Iowa State Roleplay\n"
                "**In-game Code:** vcJJf\n\n"
                "And have a great roleplay experience!"
            ),
            color=discord.Color.green()
        )
        await interaction.guild.get_channel(SESSION_CHANNEL_ID).send(content=f"<@&{SSU_ROLE_ID}>", embed=e)
        await interaction.response.send_message("Session started.", ephemeral=True)


    @app_commands.command(name="serverstop")
    @app_commands.check(is_staff)
    async def serverstop(self, interaction):
        e = discord.Embed(
            title="⛔ Server Shut Down",
            description=(
                "The server is currently shut down.\n"
                "Please do not join in-game under any circumstances unless told by SHR+\n"
                "Please be patient and keep an eye out for our next session here!"
            ),
            color=discord.Color.red()
        )
        await interaction.guild.get_channel(SESSION_CHANNEL_ID).send(embed=e)
        await interaction.response.send_message("Session stopped.", ephemeral=True)


class ReactionRolesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    class RoleButton(discord.ui.Button):
        def __init__(self, role_id, label):
            super().__init__(label=label, style=discord.ButtonStyle.primary)
            self.role_id = role_id


        async def callback(self, interaction):
            role = interaction.guild.get_role(self.role_id)
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)
                await interaction.response.send_message(f"Removed {role.name}", ephemeral=True)
            else:
                await interaction.user.add_roles(role)
                await interaction.response.send_message(f"Added {role.name}", ephemeral=True)


    @commands.Cog.listener()
    async def on_ready(self):
        channel = self.bot.get_channel(REACTION_CHANNEL_ID)
        if channel:
            view = discord.ui.View(timeout=None)
            roles = {
                SSU_ROLE_ID: "SSU Ping",
                EVENT_ROLE_ID: "Event Ping",
                ANNOUNCEMENT_ROLE_ID: "Announcement Ping",
                GIVEAWAY_ROLE_ID: "Giveaway Ping",
            }
            for role_id, label in roles.items():
                view.add_item(self.RoleButton(role_id, label))
            try:
                await channel.send("Click to toggle pings:", view=view)
            except:
                pass


class EmbedCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="embed")
    @app_commands.check(is_staff)
    async def embed(self, interaction, channel: discord.TextChannel, title: str = None, description: str = None, image_url: str = None):
        e = discord.Embed(
            title=title or discord.Embed.Empty,
            description=description or discord.Embed.Empty,
            color=discord.Color.blue()
        )
        if image_url:
            e.set_image(url=image_url)
        await channel.send(embed=e)
        await interaction.response.send_message(f"Embed sent to {channel.mention}", ephemeral=True)


class ReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="report")
    async def report(self, interaction, staff_member: discord.Member, reason: str, anonymous: bool = True):
        msg = (
            f"Anonymous report:\nStaff: {staff_member}\nReason: {reason}"
            if anonymous
            else f"Report from {interaction.user}:\nStaff: {staff_member}\nReason: {reason}"
        )
        for oid in OWNER_IDS:
            u = self.bot.get_user(oid)
            if u:
                try:
                    await u.send(msg)
                except:
                    pass
        await interaction.response.send_message("Report sent.", ephemeral=True)


class SuggestCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="suggest")
    async def suggest(self, interaction, title: str, description: str, anonymous: bool = False):
        e = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.gold(),
            timestamp=datetime.datetime.utcnow()
        )
        e.set_footer(text=f"Suggested by {'Anonymous' if anonymous else interaction.user.display_name}")
        ch = interaction.guild.get_channel(SUGGESTION_CHANNEL_ID)
        msg = await ch.send(embed=e)
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")
        await msg.add_reaction("🗨️")
        await msg.create_thread(name=f"Suggestion: {title or 'Untitled'}", auto_archive_duration=1440)
        await interaction.response.send_message("Suggestion posted!", ephemeral=True)


class GiveawayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="giveaway")
    @app_commands.check(is_staff)
    async def giveaway(self, interaction, duration: str, winners: int, prize: str):
        sec = parse_duration(duration)
        if not sec or sec < 10:
            return await interaction.response.send_message("Invalid duration.", ephemeral=True)
        end_time = int(datetime.datetime.utcnow().timestamp()) + sec
        e = discord.Embed(
            title="🎉 Giveaway!",
            description=f"Prize: **{prize}**\nReact with 🎉 to enter!\nEnds <t:{end_time}:R>",
            color=discord.Color.purple()
        )
        msg = await interaction.channel.send(embed=e)
        await msg.add_reaction("🎉")
        giveaways[str(msg.id)] = {
            "message_id": msg.id,
            "channel_id": msg.channel.id,
            "prize": prize,
            "host_id": interaction.user.id,
            "winners": winners,
            "end_time": end_time,
            "participants": []
        }
        await save_giveaways()
        await interaction.response.send_message("Giveaway started!", ephemeral=True)


class RankCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="rank")
    async def rank(self, interaction):
        d = xp_data.get(str(interaction.user.id), {"messages": 0, "level": 0})
        lvl = d["level"]
        msgs = d["messages"]
        next_lvl = next((l for l in sorted(LEVEL_ROLES) if l > lvl), None)
        desc = f"Messages: {msgs}\nLevel: {lvl}\n" + (f"Next: {next_lvl}" if next_lvl else "Max level!")
        await interaction.response.send_message(embed=discord.Embed(title=f"{interaction.user.display_name}'s Rank", description=desc, color=discord.Color.gold()), ephemeral=True)


# ---- EVENTS ----
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    for g in bot.guilds:
        if g.id != MAIN_GUILD_ID:
            await g.leave()
    g = bot.get_guild(MAIN_GUILD_ID)
    if g:
        await bot.tree.sync(guild=g)
    giveaway_check.start()


@bot.event
async def on_message(msg):
    if msg.author.bot:
        return
    if msg.guild and msg.guild.id == MAIN_GUILD_ID:
        await update_level(msg.author, msg.channel)
    await bot.process_commands(msg)


# ---- START ----
async def setup_cogs():
    await bot.add_cog(StaffCog(bot))
    await bot.add_cog(ReactionRolesCog(bot))
    await bot.add_cog(EmbedCog(bot))
    await bot.add_cog(ReportCog(bot))
    await bot.add_cog(SuggestCog(bot))
    await bot.add_cog(GiveawayCog(bot))
    await bot.add_cog(RankCog(bot))


async def main():
    async with bot:
        await setup_cogs()
        await bot.start(TOKEN)


asyncio.run(main())
