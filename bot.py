import discord
from discord.ext import commands
from discord import app_commands, ui
import os
import datetime


# === CONFIGURATION ===
TOKEN = os.environ["DISCORD_TOKEN"]
MAIN_GUILD_ID = 1371272556820041849


# Role & Channel IDs
BOD_ROLE_ID = 1371272557034209493
PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 1400683360623267870
SESSION_CHANNEL_ID = 1396277983211163668
SSU_ROLE_ID = 1371272556820041854
EVENT_ROLE_ID = 1371272556820041853
ANNOUNCE_ROLE_ID = 1371272556820041852
GIVEAWAY_ROLE_ID = 1400878647753048164
REACTION_ROLE_CHANNEL_ID = 1371272557969281159


# === INTENTS AND BOT SETUP ===
intents = discord.Intents.default()
intents.guilds = True
intents.members = True


bot = commands.Bot(command_prefix="!", intents=intents)


# === BOD CHECK ===
def is_bod():
    async def predicate(interaction: discord.Interaction):
        return any(role.id == BOD_ROLE_ID for role in interaction.user.roles)
    return app_commands.check(predicate)


# === STAFF COMMANDS COG ===
class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="promote", description="Promote a staff member")
    @is_bod()
    @app_commands.describe(user="User to promote", new_rank="New rank", reason="Promotion reason")
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_rank: str, reason: str):
        embed = discord.Embed(title="📈 Staff Promotion", color=discord.Color.green())
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="New Rank", value=new_rank)
        embed.add_field(name="Reason", value=reason)
        embed.add_field(name="Promoted By", value=interaction.user.mention)
        channel = interaction.guild.get_channel(PROMOTION_CHANNEL_ID)
        await channel.send(embed=embed)
        await interaction.response.send_message("Promotion logged.", ephemeral=True)


    @app_commands.command(name="infract", description="Issue an infraction")
    @is_bod()
    @app_commands.describe(user="User to infract", reason="Infraction reason", punishment="Warning/Strike/etc", expires="Optional expiry")
    async def infract(self, interaction: discord.Interaction, user: discord.Member, reason: str, punishment: str, expires: str = "N/A"):
        embed = discord.Embed(title="⚠️ Staff Infraction", color=discord.Color.red())
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="Punishment", value=punishment)
        embed.add_field(name="Reason", value=reason)
        embed.add_field(name="Issued By", value=interaction.user.mention)
        embed.add_field(name="Expires", value=expires)
        channel = interaction.guild.get_channel(INFRACTION_CHANNEL_ID)
        await channel.send(embed=embed)
        await interaction.response.send_message("Infraction logged.", ephemeral=True)


# === SESSION COMMANDS COG ===
class ServerSession(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="serverstart", description="Announce server start")
    @is_bod()
    async def serverstart(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Session Started",
            description=(
                "The Staff Team has started a session!\n"
                "Please remember to read all of our in-game rules before joining to prevent moderation.\n\n"
                "Server Name: Iowa State Roleplay\n"
                "In-game Code: vcJJf\n\n"
                "And have a great roleplay experience!"
            ),
            color=discord.Color.green()
        )
        role = interaction.guild.get_role(SSU_ROLE_ID)
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await channel.send(content=role.mention, embed=embed)
        await interaction.response.send_message("Session start announced!", ephemeral=True)


    @app_commands.command(name="serverstop", description="Announce server stop")
    @is_bod()
    async def serverstop(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Server Shutdown",
            description=(
                "The server is currently shut down.\n"
                "Please do not join in-game under any circumstances unless told by SHR+\n\n"
                "Please be patient and keep an eye out for our next session here!"
            ),
            color=discord.Color.red()
        )
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await channel.send(embed=embed)
        await interaction.response.send_message("Shutdown announced.", ephemeral=True)


# === REACTION ROLE COG ===
class ReactionRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="sendreactionroles", description="Send reaction roles panel")
    @is_bod()
    async def sendreactionroles(self, interaction: discord.Interaction):
        view = ui.View()
        view.add_item(ui.Button(label="Get Event Ping", custom_id="event_ping", style=discord.ButtonStyle.primary))
        view.add_item(ui.Button(label="Get Announcement Ping", custom_id="announce_ping", style=discord.ButtonStyle.success))
        view.add_item(ui.Button(label="Get Giveaway Ping", custom_id="giveaway_ping", style=discord.ButtonStyle.danger))
        view.add_item(ui.Button(label="Get SSU Ping", custom_id="ssu_ping", style=discord.ButtonStyle.secondary))


        embed = discord.Embed(
            title="🎌 Reaction Roles",
            description="Click the buttons below to toggle your ping roles!",
            color=discord.Color.blurple()
        )
        await interaction.response.send_message("Reaction roles panel sent!", ephemeral=True)
        channel = interaction.guild.get_channel(REACTION_ROLE_CHANNEL_ID)
        await channel.send(embed=embed, view=view)


@bot.event
async def on_interaction(interaction: discord.Interaction):
    if not interaction.type == discord.InteractionType.component:
        return
    member = interaction.user
    guild = interaction.guild
    roles = {
        "event_ping": guild.get_role(EVENT_ROLE_ID),
        "announce_ping": guild.get_role(ANNOUNCE_ROLE_ID),
        "giveaway_ping": guild.get_role(GIVEAWAY_ROLE_ID),
        "ssu_ping": guild.get_role(SSU_ROLE_ID),
    }
    role = roles.get(interaction.data["custom_id"])
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await interaction.response.send_message(f"Removed {role.name}", ephemeral=True)
        else:
            await member.add_roles(role)
            await interaction.response.send_message(f"Added {role.name}", ephemeral=True)


# === ERROR HANDLER ===
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)


# === ON READY ===
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    for guild in bot.guilds:
        if guild.id != MAIN_GUILD_ID:
            await guild.leave()
    guild = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
    await bot.add_cog(StaffCommands(bot))
    await bot.add_cog(ServerSession(bot))
    await bot.add_cog(ReactionRole(bot))


bot.run(TOKEN)
