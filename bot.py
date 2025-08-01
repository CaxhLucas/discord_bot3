import os
import discord
from discord.ext import commands
from discord import app_commands

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

GUILD_ID = 1371272556820041849
ALLOWED_ROLE_IDS = {
    1371272557034209493,
    1371272557034209496,
    1371272557034209498,
    1371272557034209491
}

def has_any_role(member: discord.Member, role_ids: set[int]) -> bool:
    return any(role.id in role_ids for role in member.roles)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    guild = discord.Object(id=GUILD_ID)
    try:
        synced = await bot.tree.sync(guild=guild)
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.tree.command(name="secret", description="A command only for certain roles", guild=discord.Object(id=GUILD_ID))
async def secret_command(interaction: discord.Interaction):
    if not has_any_role(interaction.user, ALLOWED_ROLE_IDS):
        await interaction.response.send_message("❌ You don’t have permission to use this command.", ephemeral=True)
        return
    await interaction.response.send_message("✅ You have access to this secret command!", ephemeral=True)

bot.run(os.environ["DISCORD_TOKEN"])
