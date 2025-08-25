import os
import discord
from discord.ext import commands
from discord import app_commands

# ====== CONFIG ======
TOKEN = os.getenv("DISCORD_TOKEN")  # Railway environment variable
MAIN_GUILD_ID = 1371272557969281159  # Your server ID
INFRACTION_CHANNEL_ID = 123456789012345678  # Replace with your infractions channel ID
BOD_ROLE_ID = 987654321098765432  # Replace with actual BOD role ID

# ====== BOT SETUP ======
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ====== BOD CHECK ======
def is_bod(interaction: discord.Interaction):
    return any(role.id == BOD_ROLE_ID for role in interaction.user.roles)

# ====== SYNC COMMANDS ======
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=MAIN_GUILD_ID))
        print(f"✅ Synced {len(synced)} commands.")
    except Exception as e:
        print(f"❌ Failed syncing: {e}")

# ====== BANNERS ======
STARTUP_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022463045863/IMG_2908.png"
SHUTDOWN_BANNER = "https://media.discordapp.net/attachments/1371272559705722978/1405970022710644796/IMG_2909.png"

# ====== AUTO RESPONDERS ======
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # --- Inactive (with optional user) ---
    if message.content.lower().startswith("-inactive"):
        parts = message.content.split(maxsplit=1)

        embed = discord.Embed(
            title="⚠️ Ticket Inactivity",
            description="This ticket will be automatically closed within 24 hours of inactivity.",
            color=discord.Color.orange()
        )

        if len(parts) == 1:
            await message.channel.send(embed=embed)
        else:
            user_text = parts[1]
            await message.channel.send(f"{user_text}", embed=embed)

        await message.delete()
        return

    # --- Other triggers ---
    if message.content.lower() == "-game":
        embed = discord.Embed(
            title="🎮 In-Game Information",
            description=(
                "To join in-game, follow these steps:\n"
                "1. Wait for an SSU.\n"
                "2. Open ER:LC on Roblox.\n"
                "3. Click the 3 lines (top right).\n"
                "4. Go to \"servers.\"\n"
                "5. Click \"Join by Code.\"\n"
                "6. Enter: **vcJJf**\n"
                "7. Enjoy your time!"
            ),
            color=discord.Color.blue()
        )
        await message.channel.send(embed=embed)
        await message.delete()

    elif message.content.lower() == "-apply":
        embed = discord.Embed(
            title="📋 Staff Applications",
            description="To apply for staff, head over to <#1371272557969281166>!",
            color=discord.Color.green()
        )
        await message.channel.send(embed=embed)
        await message.delete()

    elif message.content.lower() == "-help":
        embed = discord.Embed(
            title="❓ Need Help?",
            description="If you need assistance, open a ticket in <#1371272558221066261>.",
            color=discord.Color.blurple()
        )
        await message.channel.send(embed=embed)
        await message.delete()

    await bot.process_commands(message)

# ====== SLASH COMMANDS ======
class Management(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- /say (BOD only) ---
    @app_commands.command(name="say", description="Make the bot say something.")
    @app_commands.check(is_bod)
    async def say(self, interaction: discord.Interaction, message: str):
        await interaction.channel.send(message)
        await interaction.response.send_message("✅ Sent!", ephemeral=True)

    # --- /embed (BOD only, no timestamp) ---
    @app_commands.command(name="embed", description="Create a custom embed.")
    @app_commands.check(is_bod)
    async def embed(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        image: str = None
    ):
        embed = discord.Embed(title=title, description=description, color=discord.Color.blue())
        if image:
            embed.set_image(url=image)
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("✅ Embed sent!", ephemeral=True)

    # --- /promote (BOD only) ---
    @app_commands.command(name="promote", description="Promote a staff member.")
    @app_commands.check(is_bod)
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_role: discord.Role):
        await user.add_roles(new_role)
        embed = discord.Embed(
            title="🎉 Promotion",
            description=f"{user.mention} has been promoted to {new_role.mention}!",
            color=discord.Color.green()
        )
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("✅ Promotion done!", ephemeral=True)

    # --- /infract (BOD only, includes DM) ---
    @app_commands.command(name="infract", description="Issue an infraction to a staff member.")
    @app_commands.check(is_bod)
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
            color=discord.Color.red()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Punishment", value=punishment, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Issued By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Expires", value=expires, inline=True)

        # Send to infractions channel
        channel = interaction.guild.get_channel(INFRACTION_CHANNEL_ID)
        if channel:
            try:
                await channel.send(content=user.mention, embed=embed)
            except discord.Forbidden:
                pass

        # Always DM user
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass

        await interaction.response.send_message(
            f"✅ Infraction logged and {user.display_name} has been notified.",
            ephemeral=True
        )

    # --- /startup (BOD only) ---
    @app_commands.command(name="startup", description="Post server startup banner.")
    @app_commands.check(is_bod)
    async def startup(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🟢 Server Startup", color=discord.Color.green())
        embed.set_image(url=STARTUP_BANNER)
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("✅ Startup banner sent!", ephemeral=True)

    # --- /shutdown (BOD only) ---
    @app_commands.command(name="shutdown", description="Post server shutdown banner.")
    @app_commands.check(is_bod)
    async def shutdown(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🔴 Server Shutdown", color=discord.Color.red())
        embed.set_image(url=SHUTDOWN_BANNER)
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("✅ Shutdown banner sent!", ephemeral=True)

    # --- /suggest (Everyone) ---
    @app_commands.command(name="suggest", description="Submit a suggestion.")
    async def suggest(self, interaction: discord.Interaction, suggestion: str):
        embed = discord.Embed(
            title="💡 New Suggestion",
            description=suggestion,
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"Suggested by {interaction.user}")
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("✅ Suggestion sent!", ephemeral=True)

    # --- /report (Everyone) ---
    @app_commands.command(name="report", description="Report an issue or player.")
    async def report(self, interaction: discord.Interaction, report: str):
        embed = discord.Embed(
            title="🚨 New Report",
            description=report,
            color=discord.Color.red()
        )
        embed.set_footer(text=f"Reported by {interaction.user}")
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("✅ Report submitted!", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Management(bot), guild=discord.Object(id=MAIN_GUILD_ID))

# Run
async def main():
    async with bot:
        await setup(bot)
        await bot.start(TOKEN)

import asyncio
asyncio.run(main())
