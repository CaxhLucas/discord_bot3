import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import os
import random
import asyncio
# ====== CONFIG =======
TOKEN = os.environ["DISCORD_TOKEN"]
MAIN_GUILD_ID = 1371272556820041849
# Roles
BOD_ROLE_ID = 1371272557034209493
SUPERVISOR_ROLE_IDS = [1371272557034209491, 1371272557034209496]
STAFF_ROLE_IDS = [BOD_ROLE_ID] + SUPERVISOR_ROLE_IDS
OWNER_IDS = [902727710990811186, 1341152829967958114]
# Channels
PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 1400683360623267870
SESSION_CHANNEL_ID = 1396277983211163668
REACTION_CHANNEL_ID = 1371272557969281159
LOGGING_CHANNEL_ID = 1371272557692452884
# Ping Roles for reaction roles
SSU_ROLE_ID = 1371272556820041854
EVENT_ROLE_ID = 1371272556820041853
ANNOUNCEMENT_ROLE_ID = 1371272556820041852
GIVEAWAY_ROLE_ID = 1400878647753048164
# Leveling Roles & thresholds
LEVEL_ROLES = {
    1: 1401750387542855710,
    5: 1401750539229728919,
    10: 1401750605822824478,
    20: 1401750676911947837,
}
# ====== INTENTS =======
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)
def is_staff(interaction: discord.Interaction) -> bool:
    user_roles = [role.id for role in interaction.user.roles]
    return any(role_id in STAFF_ROLE_IDS for role_id in user_roles)
def is_bod(interaction: discord.Interaction) -> bool:
    return BOD_ROLE_ID in [role.id for role in interaction.user.roles]
def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS
# --- STAFF COMMANDS COG ---
class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    @app_commands.command(name="promote", description="Promote a staff member")
    @app_commands.check(is_staff)
    @app_commands.describe(
        user="The staff member being promoted",
        new_rank="The new rank",
        reason="Reason for promotion"
    )
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_rank: str, reason: str):
        embed = discord.Embed(
            title="📈 Staff Promotion",
            color=discord.Color.green(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="New Rank", value=new_rank, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Promoted By", value=interaction.user.mention, inline=True)
        channel = interaction.guild.get_channel(PROMOTION_CHANNEL_ID)
        # Ping promoted user
        await channel.send(content=user.mention, embed=embed)
        await interaction.response.send_message(f"Promotion logged and {user.display_name} has been pinged.", ephemeral=True)
    @app_commands.command(name="infract", description="Issue an infraction to a staff member")
    @app_commands.check(is_staff)
    @app_commands.describe(
        user="The staff member being infracted",
        reason="Reason for the infraction",
        punishment="Type of punishment (e.g., Warning, Strike)",
        expires="(Optional) Expiry date/time or condition"
    )
    async def infract(self, interaction: discord.Interaction, user: discord.Member, reason: str, punishment: str, expires: str = "N/A"):
        embed = discord.Embed(
            title="⚠️ Staff Infraction",
            color=discord.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Punishment", value=punishment, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Issued By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Expires", value=expires, inline=True)
        channel = interaction.guild.get_channel(INFRACTION_CHANNEL_ID)
        # Ping infracted user
        await channel.send(content=user.mention, embed=embed)
        await interaction.response.send_message(f"Infraction logged and {user.display_name} has been pinged.", ephemeral=True)
    @app_commands.command(name="serverstart", description="Start a session")
    @app_commands.check(is_staff)
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
            timestamp=datetime.datetime.utcnow()
        )
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await channel.send(content=f"<@&{SSU_ROLE_ID}>", embed=embed)
        await interaction.response.send_message("Session started and SSU pinged.", ephemeral=True)
    @app_commands.command(name="serverstop", description="End a session")
    @app_commands.check(is_staff)
    async def serverstop(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⛔ Session Ended",
            description=(
                "The server is currently shut down.\n"
                "Please do not join in-game under any circumstances unless told by SHR+\n\n"
                "Please be patient and keep an eye out for our next session here!"
            ),
            color=discord.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await channel.send(embed=embed)
        await interaction.response.send_message("Session ended.", ephemeral=True)
    @app_commands.command(name="embed", description="Send a custom embed to a channel")
    @app_commands.check(is_staff)
    @app_commands.describe(
        channel="Target channel",
        description="Embed description text",
        title="Optional embed title"
    )
    async def embed(self, interaction: discord.Interaction, channel: discord.TextChannel, description: str, title: str = None):
        embed = discord.Embed(
            description=description,
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.utcnow()
        )
        if title:
            embed.title = title
        await channel.send(embed=embed)
        await interaction.response.send_message(f"Embed sent to {channel.mention}", ephemeral=True)
# --- REPORT COG ---
class ReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    @app_commands.command(name="report", description="Report a staff member anonymously")
    @app_commands.describe(
        user="Staff member to report",
        reason="Reason for report"
    )
    async def report(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        embed = discord.Embed(
            title="📢 Staff Report",
            description=f"**User reported:** {user.mention}\n**Reason:** {reason}",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.utcnow()
        )
        owners = [self.bot.get_user(owner_id) for owner_id in OWNER_IDS]
        sent = False
        for owner in owners:
            if owner:
                try:
                    await owner.send(embed=embed)
                    sent = True
                except:
                    pass
        if sent:
            await interaction.response.send_message("Report sent to the owner(s). Thank you.", ephemeral=True)
        else:
            await interaction.response.send_message("Failed to send report. Owners might have DMs closed.", ephemeral=True)
# --- SUGGESTION COG ---
class SuggestionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    @app_commands.command(name="suggest", description="Submit a suggestion")
    @app_commands.check(is_staff)
    @app_commands.describe(
        name="Your name (optional for anonymous)",
        anonymous="Send anonymously?",
        title="Suggestion title",
        description="Suggestion description",
        image_url="Optional image URL"
    )
    async def suggest(self, interaction: discord.Interaction, name: str = None, anonymous: bool = False, title: str = None, description: str = None, image_url: str = None):
        sender = "Anonymous" if anonymous else (name or interaction.user.display_name)
        embed = discord.Embed(
            title=title or "Suggestion",
            description=description or "No description provided.",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_author(name=sender)
        if image_url:
            embed.set_image(url=image_url)
        # Post suggestion in a channel (use PROMOTION_CHANNEL_ID for example, or set a SUGGESTION_CHANNEL_ID)
        suggestion_channel = interaction.guild.get_channel(PROMOTION_CHANNEL_ID)
        message = await suggestion_channel.send(embed=embed)
        # Create thread for discussion
        await message.create_thread(name=f"Suggestion: {title or 'No Title'}", auto_archive_duration=60)
        await interaction.response.send_message("Suggestion submitted.", ephemeral=True)
# --- GIVEAWAY COG ---
class GiveawayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_giveaways = {}  # message_id: giveaway data
    @app_commands.command(name="giveaway", description="Start a giveaway (BOD only)")
    @app_commands.check(is_bod)
    @app_commands.describe(
        channel="Channel to host the giveaway",
        prize="Prize to win",
        winners="Number of winners",
        duration="Duration (e.g., 10m, 1h, 1d)"
    )
    async def giveaway(self, interaction: discord.Interaction, channel: discord.TextChannel, prize: str, winners: int, duration: str):
        duration_seconds = parse_duration(duration)
        if duration_seconds is None:
            return await interaction.response.send_message("Invalid duration format! Use 10m, 1h, 1d etc.", ephemeral=True)
        embed = discord.Embed(
            title="🎉 GIVEAWAY 🎉",
            description=f"Prize: **{prize}**\nHosted by: {interaction.user.mention}\nEnds: <t:{int((discord.utils.utcnow().timestamp() + duration_seconds))}:R>",
            color=discord.Color.purple(),
            timestamp=datetime.datetime.utcnow()
        )
        view = GiveawayView(self, winners)
        giveaway_message = await channel.send(embed=embed, view=view)
        self.active_giveaways[giveaway_message.id] = {
            "channel_id": channel.id,
            "prize": prize,
            "winners": winners,
            "end_time": discord.utils.utcnow().timestamp() + duration_seconds,
            "message_id": giveaway_message.id,
            "participants": set(),
            "ended": False,
            "host_id": interaction.user.id,
        }
        await interaction.response.send_message(f"Giveaway started in {channel.mention}", ephemeral=True)
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        # Optional: react to giveaway entries (if you want reaction entries)
        pass
    async def end_giveaway(self, message_id):
        giveaway = self.active_giveaways.get(message_id)
        if not giveaway or giveaway.get("ended"):
            return
        channel = self.bot.get_channel(giveaway["channel_id"])
        if not channel:
            return
        try:
            message = await channel.fetch_message(message_id)
        except:
            return
        participants = list(giveaway["participants"])
        winners_count = giveaway["winners"]
        if len(participants) == 0:
            text = f"No participants for giveaway **{giveaway['prize']}**."
        else:
            winners = random.sample(participants, min(winners_count, len(participants)))
            winner_mentions = ", ".join(f"<@{winner}>" for winner in winners)
            text = f"🎉 Congratulations {winner_mentions}! You won **{giveaway['prize']}**!"
        embed = discord.Embed(
            title="🎉 GIVEAWAY ENDED 🎉",
            description=text,
            color=discord.Color.gold(),
            timestamp=datetime.datetime.utcnow()
        )
        await message.edit(embed=embed, view=None)
        self.active_giveaways[message_id]["ended"] = True
# Giveaway button view
class GiveawayView(discord.ui.View):
    def __init__(self, cog: GiveawayCog, winners: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.winners = winners
    @discord.ui.button(label="Enter Giveaway", style=discord.ButtonStyle.success, custom_id="giveaway_enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = self.cog.active_giveaways.get(interaction.message.id)
        if giveaway is None or giveaway.get("ended"):
            return await interaction.response.send_message("This giveaway has ended.", ephemeral=True)
        if interaction.user.id in giveaway["participants"]:
            return await interaction.response.send_message("You already entered!", ephemeral=True)
        giveaway["participants"].add(interaction.user.id)
        await interaction.response.send_message("You entered the giveaway!", ephemeral=True)
# --- LEVELING COG ---
class LevelingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_message_counts = {}  # user_id: count
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None or message.guild.id != MAIN_GUILD_ID:
            return
        user_id = message.author.id
        count = self.user_message_counts.get(user_id, 0) + 1
        self.user_message_counts[user_id] = count
        # Check level thresholds from highest to lowest
        sorted_levels = sorted(LEVEL_ROLES.keys(), reverse=True)
        user_roles_ids = [role.id for role in message.author.roles]
        for lvl in sorted_levels:
            if count >= lvl and LEVEL_ROLES[lvl] not in user_roles_ids:
                role = message.guild.get_role(LEVEL_ROLES[lvl])
                if role:
                    try:
                        await message.author.add_roles(role, reason="Level up reward")
                        await message.channel.send(f"🎉 Congrats {message.author.mention}, you've leveled up to **Level {lvl}**!")
                    except:
                        pass
                break
# --- REACTION ROLES VIEW ---
class ReactionRoleButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="SSU Ping", style=discord.ButtonStyle.primary, custom_id="rr_ssu")
    async def ssu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await toggle_role(interaction, SSU_ROLE_ID)
    @discord.ui.button(label="Giveaway Ping", style=discord.ButtonStyle.primary, custom_id="rr_giveaway")
    async def giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        await toggle_role(interaction, GIVEAWAY_ROLE_ID)
    @discord.ui.button(label="Announcement Ping", style=discord.ButtonStyle.primary, custom_id="rr_announcement")
    async def announcement(self, interaction: discord.Interaction, button: discord.ui.Button):
        await toggle_role(interaction, ANNOUNCEMENT_ROLE_ID)
    @discord.ui.button(label="Event Ping", style=discord.ButtonStyle.primary, custom_id="rr_event")
    async def event(self, interaction: discord.Interaction, button: discord.ui.Button):
        await toggle_role(interaction, EVENT_ROLE_ID)
async def toggle_role(interaction: discord.Interaction, role_id: int):
    role = interaction.guild.get_role(role_id)
    if role in interaction.user.roles:
        await interaction.user.remove_roles(role)
        await interaction.response.send_message(f"Removed {role.name} role.", ephemeral=True)
    else:
        await interaction.user.add_roles(role)
        await interaction.response.send_message(f"Added {role.name} role.", ephemeral=True)
# --- HELPER FUNCTIONS ---
def parse_duration(duration_str: str):
    # Simple parsing like '10m', '1h', '1d'
    unit = duration_str[-1]
    if not duration_str[:-1].isdigit():
        return None
    amount = int(duration_str[:-1])
    if unit == "m":
        return amount * 60
    elif unit == "h":
        return amount * 3600
    elif unit == "d":
        return amount * 86400
    return None
# --- ERROR HANDLING ---
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    log_channel = bot.get_channel(LOGGING_CHANNEL_ID)
    if isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        if log_channel:
            await log_channel.send(f"{interaction.user} tried to use {interaction.command} without permission.")
    else:
        if log_channel:
            await log_channel.send(f"Error in command {interaction.command} by {interaction.user}: {error}")
        # Optional: you can send a generic error message here or ignore
# --- ON READY EVENT ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    # Leave unauthorized guilds
    for guild in bot.guilds:
        if guild.id != MAIN_GUILD_ID:
            print(f"Leaving unauthorized guild: {guild.name}")
            await guild.leave()
    # Add cogs
    await bot.add_cog(StaffCommands(bot))
    await bot.add_cog(ReportCog(bot))
    await bot.add_cog(GiveawayCog(bot))
    await bot.add_cog(LevelingCog(bot))
    await bot.add_cog(SuggestionCog(bot))
    # Sync slash commands only to main guild
    guild_obj = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild_obj)
    await bot.tree.sync(guild=guild_obj)
    # Reaction roles panel setup
    view = ReactionRoleButtons()
    channel = bot.get_channel(REACTION_CHANNEL_ID)
    if channel:
        await channel.purge(limit=5)
        await channel.send("Click the buttons below to get or remove a ping role:", view=view)
bot.run(TOKEN)


