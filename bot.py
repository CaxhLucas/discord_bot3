import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import datetime
import json
import os
import re
import random

# ---- CONFIG ----
TOKEN = os.environ["DISCORD_TOKEN"]

MAIN_GUILD_ID = 1371272556820041849
BOD_ROLE_ID = 1371272557034209493
SUPERVISOR_ROLE_IDS = [1371272557034209491, 1371272557034209496]
OWNER_IDS = [902727710990811186, 1341152829967958114]

PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 1400683360623267870
SESSION_CHANNEL_ID = 1396277983211163668
SSU_ROLE_ID = 1371272556820041854
EVENT_ROLE_ID = 1371272556820041853
ANNOUNCEMENT_ROLE_ID = 1371272556820041852
GIVEAWAY_ROLE_ID = 1400878647753048164
REACTION_CHANNEL_ID = 1371272557969281159
LOGGING_CHANNEL_ID = 1371272557692452884
SUGGESTION_CHANNEL_ID = 1401761820431355986

GIVEAWAYS_DATA_FILE = "giveaways.json"

# ---- INTENTS ----
intents = discord.Intents.all()

bot = commands.Bot(command_prefix="!", intents=intents)

# ---- HELPERS ----
def is_staff(interaction: discord.Interaction) -> bool:
    roles = getattr(interaction.user, 'roles', [])
    return any(r.id == BOD_ROLE_ID or r.id in SUPERVISOR_ROLE_IDS for r in roles)

def save_json(filename: str, data: dict):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

def load_json(filename: str) -> dict:
    if not os.path.exists(filename):
        return {}
    with open(filename, "r") as f:
        return json.load(f)

def parse_duration(duration_str: str) -> int | None:
    duration_str = duration_str.lower().replace(" ", "")
    match = re.match(r"(\d+)([smhd])", duration_str)
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    return {"s": amount, "m": amount*60, "h": amount*3600, "d": amount*86400}.get(unit)

giveaways = load_json(GIVEAWAYS_DATA_FILE)

# ---- GIVEAWAYS ----
async def save_giveaways():
    save_json(GIVEAWAYS_DATA_FILE, giveaways)

@bot.event
async def on_raw_reaction_add(payload):
    if str(payload.message_id) not in giveaways:
        return
    if str(payload.emoji) != "🎉":
        return
    if payload.user_id == bot.user.id:
        return
    g = giveaways[str(payload.message_id)]
    if payload.user_id not in g["participants"]:
        g["participants"].append(payload.user_id)
        await save_giveaways()

@tasks.loop(seconds=60)
async def giveaway_check():
    now = int(datetime.datetime.utcnow().timestamp())
    to_remove = []
    for gid, g in giveaways.items():
        if g["end_time"] <= now:
            channel = bot.get_channel(g["channel_id"])
            if not channel:
                to_remove.append(gid)
                continue
            try:
                _ = await channel.fetch_message(int(gid))
            except:
                to_remove.append(gid)
                continue
            participants = g.get("participants", [])
            if not participants:
                await channel.send(f"Giveaway for **{g['prize']}** ended, no entries.")
            else:
                winners = random.sample(participants, min(g["winners"], len(participants)))
                await channel.send(f"🎉 Giveaway ended! Congrats: {' '.join(f'<@{w}>' for w in winners)} — Prize: **{g['prize']}**!")
            to_remove.append(gid)
    for gid in to_remove:
        giveaways.pop(gid, None)
    if to_remove:
        await save_giveaways()

# ---- COGS ----
class GiveawayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="giveaway")
    @app_commands.check(is_staff)
    async def giveaway(self, interaction: discord.Interaction, duration: str, winners: int, prize: str):
        sec = parse_duration(duration)
        if not sec or sec < 10:
            return await interaction.response.send_message("Invalid duration.", ephemeral=True)
        end_time = int(datetime.datetime.utcnow().timestamp()) + sec
        e = discord.Embed(
            title="🎉 Giveaway!",
            description=f"Prize: **{prize}**\nReact with 🎉 to enter!\nEnds <t:{end_time}:R>",
            color=discord.Color.purple()
        )
        msg = await interaction.channel.send(embed=e)
        await msg.add_reaction("🎉")
        giveaways[str(msg.id)] = {
            "message_id": msg.id,
            "channel_id": msg.channel.id,
            "prize": prize,
            "host_id": interaction.user.id,
            "winners": winners,
            "end_time": end_time,
            "participants": []
        }
        await save_giveaways()
        await interaction.response.send_message("Giveaway started!", ephemeral=True)

class AutoResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        content = message.content.strip().lower()

        if content == "-inactive":
            embed = discord.Embed(
                title="⚠️ Ticket Inactivity",
                description="This ticket will be automatically closed within 24 hours of inactivity.",
                color=discord.Color.orange()
            )
            await message.channel.send(embed=embed)

        elif content == "-game":
            embed = discord.Embed(
                title="Here is some in-game information!",
                description=(
                    "To join in-game, follow these steps:\n"
                    "1. Make sure to wait for an SSU.\n"
                    "2. Once an SSU has been concurred, open Roblox, search and open Emergency Response: Liberty County.\n"
                    "3. In the top right of the screen, click the 3 lines.\n"
                    "4. Go to \"servers.\"\n"
                    "5. Click \"Join by Code.\"\n"
                    "6. Put in the code \"vcJJf\"\n"
                    "7. And have a great time!"
                ),
                color=discord.Color.blue()
            )
            await message.channel.send(embed=embed)

        elif content == "-apply":
            embed = discord.Embed(
                title="📋 Staff Applications",
                description="To apply for staff, please visit <#1371272557969281166> !",
                color=discord.Color.green()
            )
            await message.channel.send(embed=embed)

        elif content == "-help":
            embed = discord.Embed(
                title="❓ Need Assistance?",
                description="If you're in need of assistance, please open a ticket in <#1371272558221066261>.",
                color=discord.Color.blurple()
            )
            await message.channel.send(embed=embed)

async def setup(bot):
    await bot.add_cog(GiveawayCog(bot))
    await bot.add_cog(AutoResponder(bot))

# ---- EVENTS ----
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    for g in bot.guilds:
        if g.id != MAIN_GUILD_ID:
            await g.leave()
    g = bot.get_guild(MAIN_GUILD_ID)
    if g:
        await bot.tree.sync(guild=g)
    giveaway_check.start()
    await bot.add_cog(GiveawayCog(bot))
    await bot.add_cog(AutoResponder(bot))

@bot.event
async def on_message(msg):
    if msg.author.bot:
        return
    await bot.process_commands(msg)

# ---- START ----
@bot.command()
async def load_cogs(ctx):
    await bot.load_extension("__main__")
    await ctx.send("Cogs loaded")

async def main():
    async with bot:
        await bot.load_extension("__main__")
        await bot.start(TOKEN)

asyncio.run(main())
