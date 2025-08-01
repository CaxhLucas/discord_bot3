import discord
from discord.ext import commands
from discord import app_commands, Interaction, Object
import datetime
import os


# Config
TOKEN = os.environ["DISCORD_TOKEN"]
MAIN_GUILD_ID = 1371272556820041849
BOD_ROLE_ID = 1371272557034209493
PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 1400683360623267870
SESSION_CHANNEL_ID = 1396277983211163668
SSU_ROLE_ID = 1371272556820041854
EVENT_ROLE_ID = 1371272556820041853
ANNOUNCEMENT_ROLE_ID = 1371272556820041852
GIVEAWAY_ROLE_ID = 1400878647753048164
REACTION_ROLE_CHANNEL_ID = 1371272557969281159


intents = discord.Intents.default()
intents.guilds = True
intents.members = True


bot = commands.Bot(command_prefix="!", intents=intents)


# BOD check
def is_bod(interaction: discord.Interaction):
    return any(role.id == BOD_ROLE_ID for role in interaction.user.roles)


# Reaction Role View
class RoleButton(discord.ui.Button):
    def __init__(self, role_id, label, emoji):
        super().__init__(label=label, emoji=emoji, style=discord.ButtonStyle.primary)
        self.role_id = role_id


    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"❌ Removed **{role.name}** role.", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"✅ Given **{role.name}** role.", ephemeral=True)


class ReactionRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RoleButton(ANNOUNCEMENT_ROLE_ID, "Announcements", "📢"))
        self.add_item(RoleButton(EVENT_ROLE_ID, "Event Ping", "🎉"))
        self.add_item(RoleButton(GIVEAWAY_ROLE_ID, "Giveaway Ping", "🎁"))
        self.add_item(RoleButton(SSU_ROLE_ID, "SSU Ping", "🚨"))


class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="promote", description="Promote a staff member")
    @app_commands.check(is_bod)
    async def promote(self, interaction: Interaction, user: discord.Member, new_rank: str, reason: str):
        embed = discord.Embed(
            title="📈 Staff Promotion",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="New Rank", value=new_rank, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Promoted By", value=interaction.user.mention, inline=True)


        channel = interaction.guild.get_channel(PROMOTION_CHANNEL_ID)
        await channel.send(embed=embed)
        await interaction.response.send_message("Promotion logged.", ephemeral=True)


    @app_commands.command(name="infract", description="Issue an infraction to a staff member")
    @app_commands.check(is_bod)
    async def infract(self, interaction: Interaction, user: discord.Member, reason: str, punishment: str, expires: str = "N/A"):
        embed = discord.Embed(
            title="⚠️ Staff Infraction",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Punishment", value=punishment, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Issued By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Expires", value=expires, inline=True)


        channel = interaction.guild.get_channel(INFRACTION_CHANNEL_ID)
        await channel.send(embed=embed)
        await interaction.response.send_message("Infraction logged.", ephemeral=True)


    @app_commands.command(name="serverstart", description="Start a session")
    @app_commands.check(is_bod)
    async def server_start(self, interaction: Interaction):
        embed = discord.Embed(
            title="✅ Server Session Started",
            description=(
                "The Staff Team has started a session!\n"
                "Please remember to read all of our in-game rules before joining to prevent moderation.\n\n"
                "**Server Name:** Iowa State Roleplay\n"
                "**In-game Code:** `vcJJf`\n\n"
                "And have a great roleplay experience!"
            ),
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        role = interaction.guild.get_role(SSU_ROLE_ID)
        await channel.send(f"{role.mention}", embed=embed)
        await interaction.response.send_message("Session start announced.", ephemeral=True)


    @app_commands.command(name="serverstop", description="Stop a session")
    @app_commands.check(is_bod)
    async def server_stop(self, interaction: Interaction):
        embed = discord.Embed(
            title="🛑 Server Session Ended",
            description=(
                "The server is currently shut down.\n"
                "Please do not join in-game under any circumstances unless told by SHR+\n\n"
                "Please be patient and keep an eye out for our next session here!"
            ),
            color=discord.Color.red(),
            timestamp=datetime.datetime.now()
        )
        channel = interaction.guild.get_channel(SESSION_CHANNEL_ID)
        await channel.send(embed=embed)
        await interaction.response.send_message("Session stop announced.", ephemeral=True)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


    # Leave unauthorized guilds
    for guild in bot.guilds:
        if guild.id != MAIN_GUILD_ID:
            print(f"Leaving unauthorized guild: {guild.name}")
            await guild.leave()


    # Load cog
    await bot.add_cog(StaffCommands(bot))


    # Sync commands to main guild
    guild = Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)


    # Send reaction role panel (if not sent yet)
    channel = bot.get_channel(REACTION_ROLE_CHANNEL_ID)
    view = ReactionRoleView()
    already_sent = False


    async for msg in channel.history(limit=10):
        if msg.author == bot.user and len(msg.components) > 0:
            already_sent = True
            break


    if not already_sent:
        await channel.send(
            "Click the buttons below to toggle notification roles:",
            view=view
        )


bot.run(TOKEN)
