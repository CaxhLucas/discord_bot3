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


AUTHORIZED_GUILD_IDS = [1371272556820041849]  # Put your allowed server IDs here


# --- Event to auto-leave unauthorized guilds ---
@bot.event
async def on_guild_join(guild):
    if guild.id not in AUTHORIZED_GUILD_IDS:
        try:
            await guild.leave()
            print(f"Left unauthorized guild: {guild.name} ({guild.id})")
        except Exception as e:
            print(f"Failed to leave guild {guild.name}: {e}")


# --- Ready Event ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")


# --- Slash command for embed ---
@bot.tree.command(name="embed", description="Send a custom embed to a channel", guild=discord.Object(id=AUTHORIZED_GUILD_IDS[0]))
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
