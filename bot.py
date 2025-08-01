import discord
from discord.ext import commands
from discord import app_commands
import os

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.environ["DISCORD_TOKEN"]
MAIN_GUILD_ID = 1371272556820041849

ALLOWED_ROLE_IDS = [
    1371272557034209493,
    1371272557034209496,
    1371272557034209498,
    1371272557034209491
]

class EmbedSender(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="embed", description="Send a custom embed")
    @app_commands.describe(
        title="The title of the embed (optional)",
        description="The main content of the embed"
    )
    async def embed(
        self,
        interaction: discord.Interaction,
        description: str,
        title: str = None
    ):
        if not any(role.id in ALLOWED_ROLE_IDS for role in interaction.user.roles):
            await interaction.response.send_message(
                "You don’t have permission to use this command.",
                ephemeral=True
            )
            return

        embed = discord.Embed(description=description, color=discord.Color.blue())
        if title:
            embed.title = title

        await interaction.response.send_message(embed=embed)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    # Leave any server that isn’t your main one
    for guild in bot.guilds:
        if guild.id != MAIN_GUILD_ID:
            print(f"Leaving unauthorized guild: {guild.name} ({guild.id})")
            await guild.leave()

    await bot.add_cog(EmbedSender(bot))

    # Sync slash commands to your server only
    guild = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)

bot.run(TOKEN)
