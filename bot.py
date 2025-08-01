from flask import Flask
from threading import Thread
import os
import discord
from discord.ext import commands
from discord import app_commands


# --- Keep Replit alive ---
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


GUILD_ID = 1371272556820041849  # Your server ID here


# --- Events ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    guild = discord.Object(id=GUILD_ID)
    try:
        synced = await bot.tree.sync(guild=guild)
        print(f"🔁 Synced {len(synced)} command(s) to dev server")
    except Exception as e:
        print(f"❌ Sync error: {e}")


@bot.event
async def on_guild_join(guild):
    owner = (await bot.application_info()).owner
    try:
        await owner.send(f"⚠️ I was added to a new server: **{guild.name}** (ID: {guild.id}) with {guild.member_count} members.")
    except Exception as e:
        print(f"Couldn't notify owner: {e}")


# --- Slash Commands ---
@bot.tree.command(name="embed", description="Send a custom embed to a channel", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(
    channel="Channel to send the embed",
    title="Embed title",
    description="Embed description"
)
async def embed(interaction: discord.Interaction, channel: discord.TextChannel, title: str, description: str):
    embed = discord.Embed(title=title, description=description, color=0x2b2d31)
    await channel.send(embed=embed)
    await interaction.response.send_message(f"✅ Embed sent to {channel.mention}", ephemeral=True)


# --- Run ---
keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
