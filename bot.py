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

GUILD_ID = 1396295413832745020        # Your server ID
TICKET_PANEL_CHANNEL_ID = 1396296315373093076  # Support channel
TICKET_LOG_CHANNEL_ID = 1396297712441229505    # Ticket logs (future use)
OWNER_ROLE_ID = 1396309567616585850   # Owner role ID
CATEGORY_ID = 1396296249572855858     # Ticket category ID

# --- Ticket View ---
class TicketView(discord.ui.View):
    @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.green)
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            guild = interaction.guild
            category = guild.get_channel(CATEGORY_ID)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True),
                guild.get_role(OWNER_ROLE_ID): discord.PermissionOverwrite(view_channel=True)
            }
            ticket_channel = await guild.create_text_channel(
                name=f"ticket-{interaction.user.name}",
                overwrites=overwrites,
                category=category,
                reason="New ticket created"
            )
            await ticket_channel.send(f"👋 Welcome {interaction.user.mention}! A staff member will be with you shortly.")
            await interaction.response.send_message(f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            print(f"Error creating ticket: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Something went wrong creating your ticket.", ephemeral=True)

# --- Events & Commands ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    guild = discord.Object(id=GUILD_ID)
    try:
        synced = await bot.tree.sync(guild=guild)
        print(f"🔁 Synced {len(synced)} command(s) to dev server")
    except Exception as e:
        print(f"❌ Sync error: {e}")

    channel = bot.get_channel(TICKET_PANEL_CHANNEL_ID)
    if channel:
        view = TicketView()
        embed = discord.Embed(
            title="🎫 Need Support?",
            description="Click the button below to open a ticket and a staff member will assist you shortly.",
            color=0x2b2d31
        )
        embed.set_footer(text="Lucas Development | Ticket System")
        await channel.send(embed=embed, view=view)

@bot.tree.command(name="ping", description="Test if the bot is working", guild=discord.Object(id=GUILD_ID))
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong!", ephemeral=True)

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
