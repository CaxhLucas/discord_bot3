from flask import Flask
from threading import Thread
import os
import discord
from discord.ext import commands
from discord import app_commands

# --- Keep Replit/Railway alive ---
app = Flask('')

@app.route('/')
def home():
    return "I'm alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- Bot Setup ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Replace with your server ID
GUILD_ID = 1371272556820041849  

# List of allowed role IDs for /embed command
ALLOWED_ROLE_IDS = [
    1371272557034209493,
    1371272557034209496,
    1371272557034209498,
    1371272557034209491
]

def has_allowed_role(interaction: discord.Interaction) -> bool:
    # Check if user has at least one of the allowed roles
    user_roles = [role.id for role in interaction.user.roles]
    return any(role_id in user_roles for role_id in ALLOWED_ROLE_IDS)

# --- Slash Commands ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    guild = discord.Object(id=GUILD_ID)
    try:
        synced = await bot.tree.sync(guild=guild)
        print(f"🔁 Synced {len(synced)} command(s) to server {GUILD_ID}")
    except Exception as e:
        print(f"❌ Sync error: {e}")

@app_commands.command(
    name="embed",
    description="Send a custom embed to a channel",
)
@app_commands.describe(
    channel="The channel to send the embed to",
    title="Embed title",
    description="Embed description"
)
@app_commands.check(has_allowed_role)
async def embed(interaction: discord.Interaction, channel: discord.TextChannel, title: str, description: str):
    embed = discord.Embed(title=title, description=description, color=0x2b2d31)
    await channel.send(embed=embed)
    await interaction.response.send_message(f"✅ Embed sent to {channel.mention}", ephemeral=True)

# Add the command to the bot's tree for the specific guild
bot.tree.add_command(embed, guild=discord.Object(id=GUILD_ID))

# --- Run ---
keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
