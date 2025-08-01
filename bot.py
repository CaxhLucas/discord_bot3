
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

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def is_bod(interaction: discord.Interaction):
        return any(role.id == BOD_ROLE_ID for role in interaction.user.roles)

    @app_commands.command(name="promote", description="Promote a staff member")
    @app_commands.check(is_bod)
    @app_commands.describe(
        user="The staff member being promoted",
        new_rank="The new rank",
        reason="Reason for promotion"
    )
    async def promote(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        new_rank: str,
        reason: str
    ):
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
    @app_commands.describe(
        user="The staff member being infracted",
        reason="Reason for the infraction",
        punishment="Type of punishment (e.g., Warning, Strike)",
        expires="(Optional) Expiry date/time or condition"
    )
    async def infract(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str,
        punishment: str,
        expires: str = "N/A"
    ):
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

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    # Leave unauthorized guilds
    for guild in bot.guilds:
        if guild.id != MAIN_GUILD_ID:
            print(f"Leaving unauthorized guild: {guild.name}")
            await guild.leave()

    await bot.add_cog(StaffCommands(bot))

    # Sync slash commands to main server only
    guild = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)

bot.run(TOKEN)
