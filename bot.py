import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import os
import random
import asyncio
import json

# ====== CONFIG =======
TOKEN = os.environ["DISCORD_TOKEN"]
MAIN_GUILD_ID = 1371272556820041849

BOD_ROLE_ID = 1371272557034209493
SUPERVISOR_ROLE_IDS = [1371272557034209491, 1371272557034209496]
STAFF_ROLE_IDS = [BOD_ROLE_ID] + SUPERVISOR_ROLE_IDS
OWNER_IDS = [902727710990811186, 1341152829967958114]

PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 1400683360623267870
SESSION_CHANNEL_ID = 1396277983211163668
REACTION_CHANNEL_ID = 1371272557969281159
LOGGING_CHANNEL_ID = 1371272557692452884
SUGGESTION_CHANNEL_ID = 1401761820431355986

SSU_ROLE_ID = 1371272556820041854
EVENT_ROLE_ID = 1371272556820041853
ANNOUNCEMENT_ROLE_ID = 1371272556820041852
GIVEAWAY_ROLE_ID = 1400878647753048164

GIVEAWAY_FILE = "giveaways.json"

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

def parse_duration(duration_str: str):
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

def load_giveaways():
    if not os.path.isfile(GIVEAWAY_FILE):
        with open(GIVEAWAY_FILE, "w") as f:
            json.dump({}, f)
    with open(GIVEAWAY_FILE, "r") as f:
        try:
            data = json.load(f)
            return data
        except Exception:
            return {}

def save_giveaways(data):
    with open(GIVEAWAY_FILE, "w") as f:
        json.dump(data, f, indent=4)

# Message trigger handling
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.lower()
    if content.startswith("-inactive"):
        embed = discord.Embed(
            title="⚠️ Ticket Inactivity",
            description="This ticket will be automatically closed within 24 hours of inactivity",
            color=discord.Color.orange()
        )
        await message.channel.send(embed=embed)

    elif content.startswith("-game"):
        embed = discord.Embed(
            title="Here is some in-game information!",
            description=(
                "To join in-game, follow these steps:\n"
                "1. Make sure to wait for an SSU.\n"
                "2. Once an SSU has been concurred, open Roblox, search and open Emergency Response: Liberty County.\n"
                "3. In the top right of the screen, click the 3 lines.\n"
                "4. Go to 'servers.'\n"
                "5. Click 'Join by Code.'\n"
                "6. Put in the code \"vcJJf\"\n"
                "7. And have a great time!"
            ),
            color=discord.Color.blue()
        )
        await message.channel.send(embed=embed)

    elif content.startswith("-apply"):
        embed = discord.Embed(
            title="Staff Applications",
            description="To apply for staff, please visit <#1371272557969281166> !",
            color=discord.Color.green()
        )
        await message.channel.send(embed=embed)

    elif content.startswith("-help"):
        embed = discord.Embed(
            title="Need Assistance?",
            description="If you're in need of assistance, please open a ticket in <#1371272558221066261> .",
            color=discord.Color.blurple()
        )
        await message.channel.send(embed=embed)

    await bot.process_commands(message)

# Your existing cogs and bot startup code will continue here...
# (not repeated for brevity, but preserved in memory)

# At the end of your script
bot.run(TOKEN)
