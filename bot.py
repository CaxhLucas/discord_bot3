import discord
from discord.ext import commands
from discord import app_commands
import os
from datetime import datetime

intents = discord.Intents.default()
intents.guilds = True
intents.members = True  # needed for roles check

BOT_TOKEN = os.environ["DISCORD_TOKEN"]
MAIN_GUILD_ID = 1371272556820041849
PROMOTION_CHANNEL_ID = 1400683757786365972
INFRACTION_CHANNEL_ID = 1400683360623267870
BOD_ROLE_ID = 1371272557034209493  # Board of Directors role

class StaffManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def has_bod_role(self, interaction: discord.Interaction):
        return any(role.id == BOD_ROLE_ID for role in interaction.user.roles)

    @app_commands.command(name="promote", description="Promote a staff member")
    @app_commands.describe(
        user="User to promote",
        new_role="New role to assign",
        reason="Reason for promotion"
    )
    async def promote(self, interaction: discord.Interaction, user: discord.Member, new_role: discord.Role, reason: str = None):
        if not self.has_bod_role(interaction):
            await interaction.response.send_message("You don’t have permission to use this command.", ephemeral=True)
            return
        
        # Assign new role
        await user.add_roles(new_role, reason=f"Promoted by {interaction.user}")
        
        # Build embed
        embed = discord.Embed(
            title="Staff Promotion",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User Promoted", value=user.mention, inline=True)
        embed.add_field(name="New Role", value=new_role.mention, inline=True)
        embed.add_field(name="Promoted By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Date & Time (UTC)", value=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), inline=False)
        embed.add_field(name="Reason", value=reason if reason else "No reason provided", inline=False)

        channel = self.bot.get_channel(PROMOTION_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)
        else:
            await interaction.response.send_message("Promotion channel not found.", ephemeral=True)
            return
        
        await interaction.response.send_message(f"{user.mention} has been promoted to {new_role.mention}.", ephemeral=True)

    @app_commands.command(name="infract", description="Add an infraction to a staff member")
    @app_commands.describe(
        user="User to infract",
        reason="Reason for infraction"
    )
    async def infract(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        if not self.has_bod_role(interaction):
            await interaction.response.send_message("You don’t have permission to use this command.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Staff Infraction",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User Infracted", value=user.mention, inline=True)
        embed.add_field(name="Infracted By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Date & Time (UTC)", value=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)

        channel = self.bot.get_channel(INFRACTION_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)
        else:
            await interaction.response.send_message("Infraction channel not found.", ephemeral=True)
            return
        
        await interaction.response.send_message(f"{user.mention} has been infracted.", ephemeral=True)

async def leave_other_guilds(bot):
    await bot.wait_until_ready()
    for guild in bot.guilds:
        if guild.id != MAIN_GUILD_ID:
            print(f"Leaving unauthorized guild: {guild.name} ({guild.id})")
            await guild.leave()

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, case_insensitive=True)

    async def setup_hook(self):
        # Add cog
        await self.add_cog(StaffManagement(self))

        # Sync commands only in main guild
        guild = discord.Object(id=MAIN_GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def on_ready(self):
        print(f"Logged in as {self.user}")
        self.loop.create_task(leave_other_guilds(self))

bot = MyBot()
bot.run(BOT_TOKEN)
