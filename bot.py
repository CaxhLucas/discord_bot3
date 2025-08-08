import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import os
import random
import asyncio
import json

# ====== CONFIG =======
TOKEN = os.environ["DISCORD_TOKEN"]
MAIN_GUILD_ID = 1371272556820041849

BOD_ROLE_ID = 1371272557034209493
SUPERVISOR_ROLE_IDS = [1371272557034209491, 1371272557034209496]
STAFF_ROLES = [BOD_ROLE_ID] + SUPERVISOR_ROLE_IDS
OWNER_IDS = [902727710990811186, 1341152829967958114]

PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 1400683360623267870
SESSION_CHANNEL_ID = 1396277983211163668
REACTION_CHANNEL_ID = 1371272557969281159
LOGGING_CHANNEL_ID = 1371272557692452884
SUGGESTION_CHANNEL_ID = 1401761820431355986

SSU_ROLE_ID = 1371272556820041854
EVENT_ROLE_ID = 1371272556820041853
ANNOUNCEMENT_ROLE_ID = 1371272556820041852
GIVEAWAY_ROLE_ID = 1400878647753048164

GIVEAWAY_FILE = "giveaways.json"

# ---- INTENTS ----
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ====== HELPERS =======
def is_bod(interaction: discord.Interaction) -> bool:
    """Check if the invoking user is BOD."""
    try:
        return any(r.id == BOD_ROLE_ID for r in interaction.user.roles)
    except Exception:
        return False

def parse_duration(duration_str: str):
    """Parse durations like '10s', '5m', '1h', '1d' -> seconds or None."""
    if not duration_str or len(duration_str) < 2:
        return None
    unit = duration_str[-1].lower()
    num = duration_str[:-1]
    if not num.isdigit():
        return None
    amount = int(num)
    if unit == "s":
        return amount
    if unit == "m":
        return amount * 60
    if unit == "h":
        return amount * 3600
    if unit == "d":
        return amount * 86400
    return None

def load_json_file(path: str):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_json_file(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

# ====== GIVEAWAYS PERSISTENCE =======
def load_giveaways():
    return load_json_file(GIVEAWAY_FILE)

def save_giveaways(data):
    save_json_file(GIVEAWAY_FILE, data)

# active giveaways loaded at startup
ACTIVE_GIVEAWAYS = load_giveaways()

# ====== MESSAGE TRIGGERS =======
@bot.event
async def on_message(message: discord.Message):
    # keep existing behaviour and message triggers
    if message.author.bot:
        return

    content = message.content.lower()
    if content.startswith("-inactive"):
        embed = discord.Embed(
            title="⚠️ Ticket Inactivity",
            description="This ticket will be automatically closed within 24 hours of inactivity",
            color=discord.Color.orange()
        )
        await message.channel.send(embed=embed)

    elif content.startswith("-game"):
        embed = discord.Embed(
            title="Here is some in-game information!",
            description=(
                "To join in-game, follow these steps:\n"
                "1. Make sure to wait for an SSU.\n"
                "2. Once an SSU has been concurred, open Roblox, search and open Emergency Response: Liberty County.\n"
                "3. In the top right of the screen, click the 3 lines.\n"
                "4. Go to 'servers.'\n"
                "5. Click 'Join by Code.'\n"
                "6. Put in the code \"vcJJf\"\n"
                "7. And have a great time!"
            ),
            color=discord.Color.blue()
        )
        await message.channel.send(embed=embed)

    elif content.startswith("-apply"):
        embed = discord.Embed(
            title="Staff Applications",
            description="To apply for staff, please visit <#1371272557969281166> !",
            color=discord.Color.green()
        )
        await message.channel.send(embed=embed)

    elif content.startswith("-help"):
        embed = discord.Embed(
            title="Need Assistance?",
            description="If you're in need of assistance, please open a ticket in <#1371272558221066261> .",
            color=discord.Color.blurple()
        )
        await message.channel.send(embed=embed)

    # ensure other command processing continues
    await bot.process_commands(message)

# ====== REACTION ROLE BUTTONS (fixed) =======
class RoleToggleButton(discord.ui.Button):
    def __init__(self, role_id: int, label: str, custom_id: str):
        # Use secondary style to match prior look; custom_id required for persistent views
        super().__init__(label=label, style=discord.ButtonStyle.secondary, custom_id=custom_id)
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        # Toggle role for the clicking user
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("Guild not found.", ephemeral=True)
        role = guild.get_role(self.role_id)
        if not role:
            return await interaction.response.send_message("Role not found.", ephemeral=True)
        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Reaction role toggle")
                await interaction.response.send_message(f"Removed role **{role.name}**", ephemeral=True)
            else:
                await member.add_roles(role, reason="Reaction role toggle")
                await interaction.response.send_message(f"Added role **{role.name}**", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to modify your roles.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Something went wrong while toggling your role.", ephemeral=True)

class ReactionRolesView(discord.ui.View):
    def __init__(self):
        # persistent view - timeout None
        super().__init__(timeout=None)
        # Use unique custom IDs to allow persistence across restarts
        self.add_item(RoleToggleButton(ANNOUNCEMENT_ROLE_ID, "📢 Announcement Ping", custom_id="rr_announce"))
        self.add_item(RoleToggleButton(GIVEAWAY_ROLE_ID, "🎉 Giveaway Ping", custom_id="rr_giveaway"))
        self.add_item(RoleToggleButton(EVENT_ROLE_ID, "📆 Event Ping", custom_id="rr_event"))
        self.add_item(RoleToggleButton(SSU_ROLE_ID, "🚨 SSU Ping", custom_id="rr_ssu"))

# We'll ensure a single persistent message exists in REACTION_CHANNEL_ID
async def ensure_reaction_role_message():
    channel = bot.get_channel(REACTION_CHANNEL_ID)
    if not channel:
        return
    # check last 200 messages for the exact trigger message we create
    async for msg in channel.history(limit=200):
        if msg.author == bot.user and msg.content == "Click a button below to toggle pings:":
            # Make sure view is registered
            bot.add_view(ReactionRolesView())
            return
    # not found -> send it, register view
    try:
        view = ReactionRolesView()
        bot.add_view(view)  # register persistent view so buttons don't "fail"
        await channel.send("Click a button below to toggle pings:", view=view)
    except Exception as e:
        print("Failed to send reaction role message:", e)

# ====== SUGGEST & REPORT (public) =======
class SuggestCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="suggest", description="Submit a server suggestion")
    @app_commands.describe(title="Suggestion title", description="Suggestion details", image_url="Optional image URL", anonymous="Post anonymously?")
    async def suggest(self, interaction: discord.Interaction, title: str, description: str, image_url: str = None, anonymous: bool = False):
        # Build the embed with required title & description
        e = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        footer_text = "Suggested anonymously" if anonymous else f"Suggested by {interaction.user.display_name}"
        e.set_footer(text=footer_text)
        if image_url:
            e.set_image(url=image_url)
        # Post to SUGGESTION_CHANNEL_ID
        ch = interaction.guild.get_channel(SUGGESTION_CHANNEL_ID)
        if not ch:
            await interaction.response.send_message("Suggestion channel not found.", ephemeral=True)
            return
        try:
            msg = await ch.send(embed=e)
            # add reactions for voting (existing behaviour)
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")
            await msg.add_reaction("🗨️")
            # Optionally create a thread
            try:
                await msg.create_thread(name=f"Suggestion: {title or 'Untitled'}", auto_archive_duration=1440)
            except Exception:
                pass
            await interaction.response.send_message("Suggestion posted!", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Failed to post suggestion.", ephemeral=True)

class ReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="report", description="Report a staff member (anonymous)")
    @app_commands.describe(staff_member="The staff member you want to report", details="What happened")
    async def report(self, interaction: discord.Interaction, staff_member: discord.Member, details: str):
        # Build anonymous report message
        report_text = f"Anonymous Staff Report\nStaff: {staff_member} ({staff_member.id})\nServer: {interaction.guild.name} ({interaction.guild.id})\nDetails: {details}"
        # DM each owner
        sent_count = 0
        for oid in OWNER_IDS:
            owner = bot.get_user(oid)
            if owner:
                try:
                    await owner.send(report_text)
                    sent_count += 1
                except Exception:
                    pass
        await interaction.response.send_message("Your report was submitted anonymously to the server owners.", ephemeral=True)

# ====== STAFF (BOD-ONLY) COMMANDS - keep originals but restricted to BOD =======
class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # All of these commands are BOD-only via the check below
    @app_commands.command(name="promote", description="Promote a staff member")
    @app_commands.check(is_bod)
    @app_commands.describe(user="The staff member being promoted", new_rank="The new rank", reason="Reason for promotion")
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_rank: str, reason: str):
        embed = discord.Embed(
            title="📈 Staff Promotion",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="New Rank", value=new_rank, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Promoted By", value=interaction.user.mention, inline=True)
        channel = interaction.guild.get_channel(PROMOTION_CHANNEL_ID)
        if channel:
            await channel.send(content=user.mention, embed=embed)
        await interaction.response.send_message(f"Promotion logged and {user.display_name} has been pinged.", ephemeral=True)

    @app_commands.command(name="infract", description="Issue an infraction to a staff member")
    @app_commands.check(is_bod)
    @app_commands.describe(user="The staff member being infracted", reason="Reason", punishment="Punishment type", expires="Expiry info")
    async def infract(self, interaction: discord.Interaction, user: discord.Member, reason: str, punishment: str, expires: str = "N/A"):
        embed = discord.Embed(
            title="⚠️ Staff Infraction",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Punishment", value=punishment, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Issued By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Expires", value=expires, inline=True)
        channel = interaction.guild.get_channel(INFRACTION_CHANNEL_ID)
        if channel:
            await channel.send(content=user.mention, embed=embed)
        await interaction.response.send_message(f"Infraction logged and {user.display_name} has been pinged.", ephemeral=True)

    @app_commands.command(name="serverstart", description="Start a session")
    @app_commands.check(is_bod)
    async def serverstart(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="✅ Session Started",
            description=(
                "The Staff Team has started a session!\n"
                "Please remember to read all of our in-game rules before joining to prevent moderation.\n\n"
                "**Server Name:** Iowa State Roleplay\n"
                "**In-game Code:** vcJJf\n\n"
                "And have a great roleplay experience!"
            ),
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        if channel:
            await channel.send(content=f"<@&{SSU_ROLE_ID}>", embed=embed)
        await interaction.response.send_message("Session started and SSU pinged.", ephemeral=True)

    @app_commands.command(name="serverstop", description="End a session")
    @app_commands.check(is_bod)
    async def serverstop(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⛔ Session Ended",
            description=(
                "The server is currently shut down.\n"
                "Please do not join in-game under any circumstances unless told by SHR+\n\n"
                "Please be patient and keep an eye out for our next session here!"
            ),
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)
        await interaction.response.send_message("Session ended.", ephemeral=True)

    @app_commands.command(name="embed", description="Send a custom embed to a channel")
    @app_commands.check(is_bod)
    @app_commands.describe(channel="Target channel", description="Embed description text", title="Optional embed title")
    async def embed(self, interaction: discord.Interaction, channel: discord.TextChannel, description: str, title: str = None):
        embed = discord.Embed(description=description, color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
        if title:
            embed.title = title
        await channel.send(embed=embed)
        await interaction.response.send_message(f"Embed sent to {channel.mention}", ephemeral=True)

class SayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="say", description="Send a message as the bot")
    @app_commands.check(is_bod)
    @app_commands.describe(channel="Channel to send the message in", message="The message to send")
    async def say(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        await channel.send(message)
        await interaction.response.send_message(f"Message sent to {channel.mention}.", ephemeral=True)

# ====== GIVEAWAY UI + COG (persistent) =======
class GiveawayView(discord.ui.View):
    def __init__(self, cog, message_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.message_id = message_id

    @discord.ui.button(label="Enter Giveaway", style=discord.ButtonStyle.success, custom_id="giveaway_enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = self.cog.active_giveaways.get(str(self.message_id))
        if giveaway is None or giveaway.get("ended"):
            return await interaction.response.send_message("This giveaway has ended.", ephemeral=True)
        if str(interaction.user.id) in giveaway["participants"]:
            return await interaction.response.send_message("You already entered!", ephemeral=True)
        giveaway["participants"].append(str(interaction.user.id))
        self.cog.persist()
        await interaction.response.send_message("You entered the giveaway!", ephemeral=True)

    @discord.ui.button(label="Show Entrants", style=discord.ButtonStyle.secondary, custom_id="giveaway_show_entrants")
    async def show_entrants(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = self.cog.active_giveaways.get(str(self.message_id))
        if giveaway is None:
            return await interaction.response.send_message("Giveaway not found.", ephemeral=True)
        if not giveaway["participants"]:
            return await interaction.response.send_message("No one has entered yet.", ephemeral=True)
        mentions = []
        for uid in giveaway["participants"]:
            member = interaction.guild.get_member(int(uid))
            if member:
                mentions.append(member.mention)
            else:
                mentions.append(f"<@{uid}>")
        content = "**Entrants:**\n" + "\n".join(mentions)
        await interaction.response.send_message(content, ephemeral=True)

class GiveawayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_giveaways = load_giveaways()

    def persist(self):
        save_giveaways(self.active_giveaways)

    @app_commands.command(name="giveaway", description="Start a giveaway (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(channel="Channel to host the giveaway", prize="Prize to win", winners="Number of winners", duration="Duration (e.g., 10m, 1h, 1d)")
    async def giveaway(self, interaction: discord.Interaction, channel: discord.TextChannel, prize: str, winners: int, duration: str):
        duration_seconds = parse_duration(duration)
        if duration_seconds is None:
            return await interaction.response.send_message("Invalid duration format! Use 10m, 1h, 1d etc.", ephemeral=True)
        end_time = int(discord.utils.utcnow().timestamp() + duration_seconds)
        embed = discord.Embed(
            title="🎉 GIVEAWAY 🎉",
            description=f"Prize: **{prize}**\nHosted by: {interaction.user.mention}\nEnds: <t:{end_time}:R>",
            color=discord.Color.purple(),
            timestamp=discord.utils.utcnow()
        )
        giveaway_message = await channel.send(embed=embed)
        # Create view with correct message id and register it persistently
        view = GiveawayView(self, giveaway_message.id)
        try:
            self.bot.add_view(view)  # make persistent across restarts
        except Exception:
            pass
        await giveaway_message.edit(view=view)
        self.active_giveaways[str(giveaway_message.id)] = {
            "channel_id": channel.id,
            "prize": prize,
            "winners": winners,
            "end_time": end_time,
            "message_id": giveaway_message.id,
            "participants": [],
            "ended": False,
            "host_id": interaction.user.id,
        }
        self.persist()
        await interaction.response.send_message(f"Giveaway started in {channel.mention}", ephemeral=True)

    @tasks.loop(seconds=30)
    async def giveaway_checker(self):
        now = int(discord.utils.utcnow().timestamp())
        to_end = []
        for msg_id, giveaway in list(self.active_giveaways.items()):
            if not giveaway["ended"] and giveaway["end_time"] <= now:
                to_end.append(msg_id)
        for msg_id in to_end:
            await self.end_giveaway(msg_id)

    @commands.Cog.listener()
    async def on_ready(self):
        # ensure loop started and views re-registered for persistent buttons
        if not self.giveaway_checker.is_running():
            self.giveaway_checker.start()
        for msg_id, giveaway in self.active_giveaways.items():
            if not giveaway.get("ended"):
                channel = self.bot.get_channel(giveaway["channel_id"])
                if channel:
                    try:
                        message = await channel.fetch_message(int(msg_id))
                        view = GiveawayView(self, int(msg_id))
                        # Register persistent view so buttons do not fail
                        try:
                            self.bot.add_view(view)
                        except Exception:
                            pass
                        await message.edit(view=view)
                    except Exception:
                        pass

    async def end_giveaway(self, message_id):
        giveaway = self.active_giveaways.get(str(message_id))
        if not giveaway or giveaway.get("ended"):
            return
        channel = self.bot.get_channel(giveaway["channel_id"])
        if not channel:
            return
        try:
            message = await channel.fetch_message(int(message_id))
        except Exception:
            return
        participants = giveaway["participants"]
        winners_count = giveaway["winners"]
        if len(participants) == 0:
            text = f"No participants for giveaway **{giveaway['prize']}**."
        else:
            winner_ids = random.sample(participants, min(winners_count, len(participants)))
            winner_mentions = ", ".join(f"<@{winner}>" for winner in winner_ids)
            text = f"🎉 Congratulations {winner_mentions}! You won **{giveaway['prize']}**!"
        embed = discord.Embed(title="🎉 GIVEAWAY ENDED 🎉", description=text, color=discord.Color.gold(), timestamp=discord.utils.utcnow())
        try:
            await message.edit(embed=embed, view=None)
        except Exception:
            pass
        self.active_giveaways[str(message_id)]["ended"] = True
        self.persist()

# ====== BOOT / COG REGISTRATION / SYNC =======
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    # leave other guilds for security
    for guild in list(bot.guilds):
        if guild.id != MAIN_GUILD_ID:
            try:
                await guild.leave()
                print(f"Left guild {guild.name} ({guild.id})")
            except Exception:
                pass

    # register cogs and commands
    try:
        await bot.add_cog(StaffCommands(bot))
        await bot.add_cog(SayCog(bot))
        await bot.add_cog(GiveawayCog(bot))
        await bot.add_cog(SuggestCog(bot))
        await bot.add_cog(ReportCog(bot))
    except Exception as e:
        print("Error adding cogs:", e)

    # sync to guild (fast)
    try:
        guild_obj = discord.Object(id=MAIN_GUILD_ID)
        bot.tree.copy_global_to(guild=guild_obj)
        synced = await bot.tree.sync(guild=guild_obj)
        print(f"Synced {len(synced)} commands to guild {MAIN_GUILD_ID}")
    except Exception as e:
        print("Command sync failed:", e)

    # Ensure reaction role message exists and View registered
    await ensure_reaction_role_message()

    # For any existing giveaways, ensure views are registered (also handled in GiveawayCog.on_ready)
    # But we add a safety registration here as well.
    for gid in list(ACTIVE_GIVEAWAYS.keys()):
        try:
            view = GiveawayView(bot.get_cog("GiveawayCog"), int(gid))
            try:
                bot.add_view(view)
            except Exception:
                pass
        except Exception:
            pass

# ====== RAW REACTION HANDLERS (for backwards compatibility if used) =======
# (Optional) if you still plan to use reaction emoji entries alongside buttons:
@bot.event
async def on_raw_reaction_add(payload):
    # legacy: if reaction used on a giveaway message, add participant
    if str(payload.message_id) in ACTIVE_GIVEAWAYS:
        if str(payload.emoji) == "🎉":
            if payload.user_id == bot.user.id:
                return
            g = ACTIVE_GIVEAWAYS[str(payload.message_id)]
            if payload.user_id not in g["participants"]:
                g["participants"].append(payload.user_id)
                save_giveaways(ACTIVE_GIVEAWAYS)

@bot.event
async def on_raw_reaction_remove(payload):
    if str(payload.message_id) in ACTIVE_GIVEAWAYS:
        if str(payload.emoji) == "🎉":
            g = ACTIVE_GIVEAWAYS[str(payload.message_id)]
            if payload.user_id in g.get("participants", []):
                g["participants"].remove(payload.user_id)
                save_giveaways(ACTIVE_GIVEAWAYS)

# ====== START BOT =======
if __name__ == "__main__":
    # safety checks
    if not TOKEN:
        print("DISCORD_TOKEN environment variable not set. Exiting.")
    else:
        bot.run(TOKEN)
