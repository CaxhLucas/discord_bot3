import discord
from discord.ext import commands
from discord import app_commands
import os

# ====== CONFIG =======
TOKEN = os.environ["DISCORD_TOKEN"]
MAIN_GUILD_ID = 1371272556820041849

BOD_ROLE_ID = 1371272557034209493
INFRACTION_CHANNEL_ID = 1400683360623267870
SUGGESTION_CHANNEL_ID = 1401761820431355986

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="-", intents=intents)

# ====== PERMISSION CHECKS =======
def is_bod(interaction: discord.Interaction) -> bool:
    return BOD_ROLE_ID in [role.id for role in interaction.user.roles]

# ====== STAFF COMMANDS =======
class StaffCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="infract", description="Issue an infraction to a staff member")
    @app_commands.check(is_bod)
    @app_commands.describe(user="Staff member", reason="Reason", punishment="Punishment", expires="Optional expiry")
    async def infract(self, interaction: discord.Interaction, user: discord.Member, reason: str, punishment: str, expires: str = "N/A"):
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

        # Always DM the staff member
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass

        await interaction.response.send_message(
            f"Infraction logged and {user.display_name} has been notified.", 
            ephemeral=True
        )

# ====== PUBLIC COMMANDS =======
class PublicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="suggest", description="Submit a suggestion")
    @app_commands.describe(title="Suggestion title", description="Suggestion details", image_url="Optional image", anonymous="Remain anonymous?")
    async def suggest(self, interaction: discord.Interaction, title: str, description: str, image_url: str = None, anonymous: bool = False):
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.green()
        )
        if image_url:
            embed.set_image(url=image_url)
        author_name = "Anonymous" if anonymous else interaction.user.display_name
        embed.set_footer(text=f"Suggested by {author_name}")
        channel = interaction.guild.get_channel(SUGGESTION_CHANNEL_ID)
        await channel.send(embed=embed)
        await interaction.response.send_message("Your suggestion has been submitted.", ephemeral=True)

# ====== MESSAGE TRIGGERS =======
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.lower()

    if content.startswith("-inactive"):
        parts = message.content.split(maxsplit=1)
        if len(parts) > 1:
            target = parts[1]
            await message.channel.send(
                f"{target}\n\n⚠️ **Ticket Inactivity**\nThis ticket will be automatically closed within 24 hours of inactivity."
            )
        else:
            await message.channel.send(
                "⚠️ **Ticket Inactivity**\nThis ticket will be automatically closed within 24 hours of inactivity."
            )
        await message.delete()

    elif content == "-game":
        await message.channel.send("🎮 A game session is starting soon, get ready!")
        await message.delete()

    elif content == "-apply":
        await message.channel.send("📋 Apply for staff here: [Your Application Link]")
        await message.delete()

    elif content == "-help":
        await message.channel.send("❓ Need help? A staff member will assist you shortly.")
        await message.delete()

# ====== BOT EVENTS =======
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    await bot.add_cog(StaffCommands(bot))
    await bot.add_cog(PublicCommands(bot))

    guild_obj = discord.Object(id=MAIN_GUILD_ID)
    bot.tree.copy_global_to(guild=guild_obj)
    await bot.tree.sync(guild=guild_obj)
    print("Slash commands synced.")

bot.run(TOKEN)
