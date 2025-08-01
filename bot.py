import discord
from discord.ext import commands
from discord import app_commands
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
REACTION_CHANNEL_ID = 1371272557969281159


intents = discord.Intents.default()
intents.guilds = True
intents.members = True


bot = commands.Bot(command_prefix="!", intents=intents)


def is_bod(interaction: discord.Interaction):
    return any(role.id == BOD_ROLE_ID for role in interaction.user.roles)


class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="promote", description="Promote a staff member")
    @app_commands.check(is_bod)
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_rank: str, reason: str):
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


    @app_commands.command(name="infract", description="Issue an infraction")
    @app_commands.check(is_bod)
    async def infract(self, interaction: discord.Interaction, user: discord.Member, reason: str, punishment: str, expires: str = "N/A"):
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
            timestamp=datetime.datetime.now()
        )
        await interaction.guild.get_channel(SESSION_CHANNEL_ID).send(content=f"<@&{SSU_ROLE_ID}>", embed=embed)
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
            timestamp=datetime.datetime.now()
        )
        await interaction.guild.get_channel(SESSION_CHANNEL_ID).send(embed=embed)
        await interaction.response.send_message("Session ended.", ephemeral=True)


    @app_commands.command(name="embed", description="Send a custom embed to a channel")
    @app_commands.check(is_bod)
    async def embed(self, interaction: discord.Interaction, channel: discord.TextChannel, description: str, title: str = None):
        embed = discord.Embed(
            description=description,
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now()
        )
        if title:
            embed.title = title
        await channel.send(embed=embed)
        await interaction.response.send_message(f"Embed sent to {channel.mention}", ephemeral=True)


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


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


    for guild in bot.guilds:
        if guild.id != MAIN_GUILD_ID:
            print(f"Leaving unauthorized guild: {guild.name}")
            await guild.leave()


    await bot.add_cog(StaffCommands(bot))


    # Sync slash commands
    guild = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)


    # Reaction Roles Panel
    view = ReactionRoleButtons()
    channel = bot.get_channel(REACTION_CHANNEL_ID)
    await channel.purge(limit=5)
    await channel.send("Click the buttons below to get or remove a ping role:", view=view)


bot.run(TOKEN)
