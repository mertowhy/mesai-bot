import discord
from discord import app_commands
from discord.ext import commands
import time
import os
import logging

logger = logging.getLogger("sahp_bot")

def format_duration(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if hours > 0:
        parts.append(f"{hours} saat")
    if minutes > 0:
        parts.append(f"{minutes} dakika")
    if secs > 0 or not parts:
        parts.append(f"{secs} saniye")
    return " ".join(parts)

class MesaiCog(commands.Cog, name="Mesai Takip"):
    def __init__(self, bot):
        self.bot = bot
        self.active_channel_id = int(os.getenv("AKTIF_MESAI_CHANNEL_ID", 0))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        if not self.active_channel_id:
            logger.warning("AKTIF_MESAI_CHANNEL_ID environment variable is not configured correctly.")
            return

        # Check if user entered active channel
        joined = (after.channel and after.channel.id == self.active_channel_id) and \
                 (not before.channel or before.channel.id != self.active_channel_id)
                 
        # Check if user left active channel
        left = (before.channel and before.channel.id == self.active_channel_id) and \
               (not after.channel or after.channel.id != self.active_channel_id)

        current_time = int(time.time())

        if joined:
            self.bot.db.start_session(str(member.id), member.display_name, current_time)
            logger.info(f"{member.display_name} ({member.id}) entered Aktif Mesai channel.")

        elif left:
            duration = self.bot.db.end_session(str(member.id), current_time)
            logger.info(f"{member.display_name} ({member.id}) left Aktif Mesai channel. Duration: {duration}s")
            
            # Send a DM to the member telling them how long they spent (optional but highly engaging)
            try:
                if duration > 10:  # Only DM if they spent more than 10 seconds to avoid spamming
                    formatted_time = format_duration(duration)
                    embed = discord.Embed(
                        title="Mesai Tamamlandı",
                        description=f"SAHP Aktif Mesai ses kanalındaki oturumunuz sonlandı.\n\n**Oturum Süresi:** {formatted_time}",
                        color=discord.Color.blue()
                    )
                    embed.set_footer(text="San Andreas Highway Patrol")
                    await member.send(embed=embed)
            except discord.Forbidden:
                logger.warning(f"Could not send DM to {member.display_name} (DMs disabled).")
            except Exception as e:
                logger.error(f"Failed to send session feedback to {member.display_name}: {e}")

    @app_commands.command(name="mesai", description="Toplam mesai sürenizi görüntüler.")
    async def mesai_sorgu(self, interaction: discord.Interaction):
        total_seconds = self.bot.db.get_total_time(str(interaction.user.id))
        formatted_time = format_duration(total_seconds)
        
        embed = discord.Embed(
            title="👮 SAHP Kişisel Mesai Bilgisi",
            description=f"Merhaba **{interaction.user.display_name}**, bugüne kadarki toplam aktif mesai süreniz:\n\n**⏱️ Toplam Süre:** {formatted_time}",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
        embed.set_footer(text="San Andreas Highway Patrol • Güvenli ve Huzurlu Otobanlar")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="mesai-sorgula", description="Belirtilen memurun mesai süresini sorgular.")
    @app_commands.describe(kullanici="Sorgulanacak memur")
    @app_commands.default_permissions(manage_guild=True)
    async def mesai_sorgula_admin(self, interaction: discord.Interaction, kullanici: discord.Member):
        total_seconds = self.bot.db.get_total_time(str(kullanici.id))
        formatted_time = format_duration(total_seconds)
        
        embed = discord.Embed(
            title="📋 SAHP Memur Mesai Bilgisi",
            description=f"**Memur:** {kullanici.mention} ({kullanici.display_name})\n\n**⏱️ Toplam Mesai Süresi:** {formatted_time}",
            color=discord.Color.dark_teal()
        )
        embed.set_thumbnail(url=kullanici.display_avatar.url if kullanici.display_avatar else None)
        embed.set_footer(text=f"Sorgulayan: {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="mesai-temizle", description="Bir memurun veya tüm veritabanının mesai sürelerini sıfırlar.")
    @app_commands.describe(kullanici="Mesaisi sıfırlanacak memur (boş bırakılırsa herkesinki sıfırlanır)")
    @app_commands.default_permissions(administrator=True)
    async def mesai_temizle(self, interaction: discord.Interaction, kullanici: discord.Member = None):
        if kullanici:
            self.bot.db.reset_mesai(str(kullanici.id))
            await interaction.response.send_message(
                f"✅ {kullanici.mention} adlı memurun tüm mesai kayıtları başarıyla sıfırlandı.", 
                ephemeral=True
            )
        else:
            # Send confirmation prompt (since this deletes everything, we ask for confirmation or warn)
            self.bot.db.reset_mesai()
            await interaction.response.send_message(
                "⚠️ **Veritabanındaki tüm memurların mesai süreleri sıfırlandı!**", 
                ephemeral=True
            )

    @app_commands.command(name="mesai-liste", description="En çok mesai yapan memurları listeler.")
    async def mesai_liste(self, interaction: discord.Interaction):
        totals = self.bot.db.get_all_totals()
        if not totals:
            await interaction.response.send_message("❌ Sunucuda henüz kayıtlı mesai verisi bulunmamaktadır.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🏆 SAHP En Aktif Memurlar Listesi",
            color=discord.Color.blue()
        )
        
        leaderboard_text = ""
        for index, row in enumerate(totals[:15], start=1):
            formatted_time = format_duration(row['total_duration'])
            member = interaction.guild.get_member(int(row['user_id']))
            mention = member.mention if member else f"@{row['username']}"
            
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            medal = medals.get(index, f"`#{index}`")
            leaderboard_text += f"{medal} {mention} - **{formatted_time}**\n"

        embed.description = leaderboard_text
        embed.set_footer(text="San Andreas Highway Patrol")
        await interaction.response.send_message(embed=embed, ephemeral=False)

async def setup(bot):
    await bot.add_cog(MesaiCog(bot))
