import discord
from discord import app_commands
from discord.ext import commands, tasks
import time
import os
import logging
import datetime

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

def check_active_mazeret(db, user_id: str) -> dict:
    import datetime
    try:
        mazerets = db.get_active_mazerets(user_id)
        if not mazerets:
            return None
            
        now = datetime.datetime.now()
        for m in mazerets:
            dates_str = m.get("dates", "")
            parts = [p.strip() for p in dates_str.split("-")]
            if len(parts) == 2:
                start_dt = datetime.datetime.strptime(parts[0], "%d.%m.%Y")
                end_dt = datetime.datetime.strptime(parts[1], "%d.%m.%Y")
                end_dt = end_dt.replace(hour=23, minute=59, second=59)
                if start_dt <= now <= end_dt:
                    return m
            elif len(parts) == 1:
                dt = datetime.datetime.strptime(parts[0], "%d.%m.%Y")
                start_dt = dt.replace(hour=0, minute=0, second=0)
                end_dt = dt.replace(hour=23, minute=59, second=59)
                if start_dt <= now <= end_dt:
                    return m
    except Exception:
        pass
    return None

def get_progress_bar_and_text(weekly_seconds: int) -> tuple[str, str]:
    target_hours = int(os.getenv("HAFTALIK_HEDEF_SAAT", 10))
    target_seconds = target_hours * 3600
    
    if target_seconds <= 0:
        return "", ""
        
    percent = min(100, int((weekly_seconds / target_seconds) * 100))
    bar_length = 10
    filled_length = int(bar_length * percent / 100)
    bar = "🟩" * filled_length + "⬜" * (bar_length - filled_length)
    
    progress_text = f"\n**🎯 Haftalık Hedef:** {target_hours} saat\n**📊 Haftalık Durum:** {bar} %{percent}"
    return progress_text, f"{percent}%"

class MesaiSummaryView(discord.ui.View):
    def __init__(self, target_member_id: int, session_duration: int, today_seconds: int, weekly_seconds: int, total_seconds: int):
        super().__init__(timeout=1800) # 30 minutes timeout
        self.target_member_id = target_member_id
        self.session_duration = session_duration
        self.today_seconds = today_seconds
        self.weekly_seconds = weekly_seconds
        self.total_seconds = total_seconds

    @discord.ui.button(label="Mesai Özetini Gör", style=discord.ButtonStyle.primary, emoji="📋")
    async def view_summary(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_member_id:
            await interaction.response.send_message(
                f"❌ Bu özet başka bir memura aittir. Kendi mesai bilgilerinizi sorgulamak için `/mesai` komutunu kullanabilirsiniz.", 
                ephemeral=True
            )
            return
            
        formatted_session = format_duration(self.session_duration)
        formatted_today = format_duration(self.today_seconds)
        formatted_weekly = format_duration(self.weekly_seconds)
        formatted_total = format_duration(self.total_seconds)
        
        # Get progress bar
        progress_text, _ = get_progress_bar_and_text(self.weekly_seconds)
        
        embed = discord.Embed(
            title="👮 San Andreas Highway Patrol — Mesai Raporu",
            description=f"Merhaba {interaction.user.mention}, **Aktif Mesai** ses kanalındaki oturumunuz başarıyla sonlandırıldı.",
            color=0x1F4E79, # Custom dark blue color
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(name="⏱️ Son Oturum Süresi", value=f"`{formatted_session}`", inline=True)
        embed.add_field(name="📅 Bugünkü Toplam", value=f"`{formatted_today}`", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        
        embed.add_field(name="📊 Son 7 Gün", value=f"`{formatted_weekly}`", inline=True)
        embed.add_field(name="🏆 Genel Toplam", value=f"`{formatted_total}`", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        
        if progress_text:
            clean_progress = progress_text.strip().replace("**🎯 Haftalık Hedef:**", "🎯 **Haftalık Hedef:**").replace("**📊 Haftalık Durum:**", "📊 **Haftalık Durum:**")
            embed.add_field(name="📈 İlerleme Durumu", value=clean_progress, inline=False)
            
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        embed.set_footer(text="San Andreas Highway Patrol • Command Staff")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

class MesaiCog(commands.Cog, name="Mesai Takip"):
    def __init__(self, bot):
        self.bot = bot
        self.active_channel_id = int(os.getenv("AKTIF_MESAI_CHANNEL_ID", 0))
        self.weekly_report_loop.start()

    def cog_unload(self):
        self.weekly_report_loop.cancel()

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

        # Helper to find mesai channel (prioritizes ID, falls back to name)
        async def get_mesai_channel(guild):
            # 1. Try to find by configured channel ID
            log_channel_id = os.getenv("MESAI_LOG_CHANNEL_ID")
            if log_channel_id:
                try:
                    # Check local cache first
                    channel = guild.get_channel(int(log_channel_id))
                    if channel:
                        return channel
                    # Fallback to API fetch (forces Discord to return the channel)
                    channel = await self.bot.fetch_channel(int(log_channel_id))
                    if channel:
                        return channel
                except Exception as e:
                    logger.warning(f"Could not resolve channel by ID {log_channel_id}: {e}")

            # 2. Fallback to name search
            channel = discord.utils.get(guild.text_channels, name="「👮」mesai")
            if not channel:
                for tc in guild.text_channels:
                    if "mesai" in tc.name.lower():
                        return tc
            return channel

        if joined:
            self.bot.db.start_session(str(member.id), member.display_name, current_time)
            logger.info(f"{member.display_name} ({member.id}) entered Aktif Mesai channel.")
            
            # Send entry warning message
            try:
                mesai_channel = await get_mesai_channel(member.guild)
                warning_message = f"🚨 {member.mention} **Mesaiye girdin!** Unutma, mesaide olmadığın takdirde bu ses kanalında bulunman ceza almana yol açabilir."
                
                if mesai_channel:
                    await mesai_channel.send(warning_message)
                else:
                    await after.channel.send(warning_message)
            except Exception as e:
                logger.error(f"Failed to send entry warning message: {e}")

        elif left:
            duration = self.bot.db.end_session(str(member.id), current_time)
            logger.info(f"{member.display_name} ({member.id}) left Aktif Mesai channel. Duration: {duration}s")
            
            # Fetch weekly and all-time totals
            today_seconds = self.bot.db.get_today_time(str(member.id))
            weekly_seconds = self.bot.db.get_weekly_time(str(member.id))
            total_seconds = self.bot.db.get_total_time(str(member.id))
            
            # Send public message with a button for ephemeral statistics
            try:
                if duration > 5:  # Only post if they spent more than 5 seconds
                    view = MesaiSummaryView(member.id, duration, today_seconds, weekly_seconds, total_seconds)
                    mesai_channel = await get_mesai_channel(member.guild)
                    
                    exit_message = f"👋 {member.mention} **mesaiden ayrıldı.** Özetini görmek için tıkla:"
                    
                    if mesai_channel:
                        await mesai_channel.send(
                            content=exit_message, 
                            view=view, 
                            delete_after=120  # Automatically delete message after 120 seconds
                        )
                    else:
                        await before.channel.send(
                            content=exit_message, 
                            view=view, 
                            delete_after=120
                        )
            except Exception as e:
                logger.error(f"Failed to send session feedback button to channel: {e}")

    @app_commands.command(name="mesai", description="Toplam mesai sürenizi görüntüler.")
    async def mesai_sorgu(self, interaction: discord.Interaction):
        total_seconds = self.bot.db.get_total_time(str(interaction.user.id))
        formatted_time = format_duration(total_seconds)
        weekly_seconds = self.bot.db.get_weekly_time(str(interaction.user.id))
        formatted_weekly = format_duration(weekly_seconds)
        
        progress_text, _ = get_progress_bar_and_text(weekly_seconds)
        
        active_mazeret = check_active_mazeret(self.bot.db, str(interaction.user.id))
        mazeret_text = ""
        if active_mazeret:
            mazeret_text = f"\n\n💤 **Mazeret Durumu:** Aktif Mazeretiniz Var ({active_mazeret['dates']})\n**Gerekçe:** {active_mazeret['reason']}"
        
        embed = discord.Embed(
            title="👮 SAHP Kişisel Mesai Bilgisi",
            description=(
                f"Merhaba **{interaction.user.display_name}**, mesai durumunuz aşağıda listelenmiştir:\n\n"
                f"**⏱️ Toplam Süre:** {formatted_time}\n"
                f"**📅 Bu Haftaki Süre:** {formatted_weekly}"
                f"{progress_text}"
                f"{mazeret_text}"
            ),
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
        weekly_seconds = self.bot.db.get_weekly_time(str(kullanici.id))
        formatted_weekly = format_duration(weekly_seconds)
        
        progress_text, _ = get_progress_bar_and_text(weekly_seconds)
        
        active_mazeret = check_active_mazeret(self.bot.db, str(kullanici.id))
        mazeret_text = ""
        if active_mazeret:
            mazeret_text = f"\n\n💤 **Mazeret Durumu:** Aktif Mazereti Var ({active_mazeret['dates']})\n**Gerekçe:** {active_mazeret['reason']}"
            
        embed = discord.Embed(
            title="📋 SAHP Memur Mesai Bilgisi",
            description=(
                f"**Memur:** {kullanici.mention} ({kullanici.display_name})\n\n"
                f"**⏱️ Toplam Mesai Süresi:** {formatted_time}\n"
                f"**📅 Bu Haftaki Süre:** {formatted_weekly}"
                f"{progress_text}"
                f"{mazeret_text}"
            ),
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
            
            active_mazeret = check_active_mazeret(self.bot.db, row['user_id'])
            mazeret_badge = " 💤" if active_mazeret else ""
            
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            medal = medals.get(index, f"`#{index}`")
            leaderboard_text += f"{medal} {mention}{mazeret_badge} - **{formatted_time}**\n"

        embed.description = leaderboard_text
        embed.set_footer(text="San Andreas Highway Patrol")
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="mesai-hafta", description="Son 7 günde en çok mesai yapan memurları listeler.")
    async def mesai_hafta(self, interaction: discord.Interaction):
        totals = self.bot.db.get_all_weekly_totals()
        if not totals:
            await interaction.response.send_message("❌ Son 7 günde kayıtlı mesai verisi bulunmamaktadır.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🏆 SAHP Haftalık En Aktif Memurlar Listesi (Son 7 Gün)",
            color=discord.Color.green()
        )
        
        leaderboard_text = ""
        for index, row in enumerate(totals[:15], start=1):
            formatted_time = format_duration(row['total_duration'])
            member = interaction.guild.get_member(int(row['user_id']))
            mention = member.mention if member else f"@{row['username']}"
            
            active_mazeret = check_active_mazeret(self.bot.db, row['user_id'])
            mazeret_badge = " 💤" if active_mazeret else ""
            
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            medal = medals.get(index, f"`#{index}`")
            leaderboard_text += f"{medal} {mention}{mazeret_badge} - **{formatted_time}**\n"

        embed.description = leaderboard_text
        embed.set_footer(text="San Andreas Highway Patrol • Son 7 Günlük Rapor")
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="mesai-rapor", description="Belirtilen iki tarih arasındaki mesai sürelerini raporlar ve CSV dosyası gönderir.")
    @app_commands.describe(
        baslangic="Başlangıç tarihi (GG.AA.YYYY)",
        bitis="Bitiş tarihi (GG.AA.YYYY)"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def mesai_rapor(self, interaction: discord.Interaction, baslangic: str, bitis: str):
        import datetime
        import io
        import csv
        
        await interaction.response.defer(ephemeral=False)
        
        try:
            start_dt = datetime.datetime.strptime(baslangic.strip(), "%d.%m.%Y")
            start_dt = start_dt.replace(hour=0, minute=0, second=0)
            start_ts = int(start_dt.timestamp())
            
            end_dt = datetime.datetime.strptime(bitis.strip(), "%d.%m.%Y")
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
            end_ts = int(end_dt.timestamp())
        except ValueError:
            await interaction.followup.send("❌ Geçersiz tarih formatı. Lütfen `GG.AA.YYYY` formatında yazın (Örn: 01.06.2026).", ephemeral=True)
            return

        totals = self.bot.db.get_range_totals(start_ts, end_ts)
        if not totals:
            await interaction.followup.send(f"❌ `{baslangic}` - `{bitis}` tarihleri arasında mesai kaydı bulunamadı.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📋 SAHP Mesai Raporu ({baslangic} - {bitis})",
            color=discord.Color.purple()
        )
        
        leaderboard_text = ""
        for index, row in enumerate(totals[:15], start=1):
            formatted_time = format_duration(row['total_duration'])
            member = interaction.guild.get_member(int(row['user_id']))
            mention = member.mention if member else f"@{row['username']}"
            
            active_mazeret = check_active_mazeret(self.bot.db, row['user_id'])
            mazeret_badge = " 💤" if active_mazeret else ""
            
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            medal = medals.get(index, f"`#{index}`")
            leaderboard_text += f"{medal} {mention}{mazeret_badge} - **{formatted_time}**\n"

        embed.description = leaderboard_text
        embed.set_footer(text="San Andreas Highway Patrol • Özel Tarih Raporu")
        
        try:
            csv_buffer = io.StringIO()
            csv_writer = csv.writer(csv_buffer)
            csv_buffer.write('\ufeff')
            csv_writer.writerow(["Sira", "Memur ID", "Memur Adi", "Toplam Mesai (Saniye)", "Toplam Mesai (Formatli)"])
            
            for index, row in enumerate(totals, start=1):
                formatted_time = format_duration(row['total_duration'])
                csv_writer.writerow([
                    index,
                    row['user_id'],
                    row['username'],
                    row['total_duration'],
                    formatted_time
                ])
                
            csv_buffer.seek(0)
            file_data = discord.File(
                fp=io.BytesIO(csv_buffer.getvalue().encode('utf-8-sig')), 
                filename=f"mesai_rapor_{baslangic}_{bitis}.csv"
            )
            await interaction.followup.send(embed=embed, file=file_data)
        except Exception as e:
            logger.error(f"Error generating or sending CSV report: {e}")
            await interaction.followup.send(embed=embed)

    TR_TZ = datetime.timezone(datetime.timedelta(hours=3))

    @tasks.loop(time=datetime.time(hour=23, minute=59, tzinfo=TR_TZ))
    async def weekly_report_loop(self):
        now = datetime.datetime.now(self.TR_TZ)
        if now.weekday() != 6:
            return
            
        logger.info("Executing automatic weekly mesai report...")
        totals = self.bot.db.get_all_weekly_totals()
        if not totals:
            logger.info("No weekly totals found for report.")
            return

        report_channel_id = int(os.getenv("HAFTALIK_RAPOR_CHANNEL_ID", 1520717176787701801))
        
        guild_id = os.getenv("GUILD_ID")
        guild = self.bot.get_guild(int(guild_id)) if guild_id else None
        if not guild and self.bot.guilds:
            guild = self.bot.guilds[0]
            
        if not guild:
            logger.error("Could not find any guild to process weekly report.")
            return
            
        channel = guild.get_channel(report_channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(report_channel_id)
            except Exception as e:
                logger.error(f"Failed to fetch weekly report channel with ID {report_channel_id}: {e}")
                
        if channel:
            embed = discord.Embed(
                title="📊 SAHP Haftalık Mesai Raporu",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            
            leaderboard_text = ""
            for index, row in enumerate(totals[:15], start=1):
                formatted_time = format_duration(row['total_duration'])
                member = guild.get_member(int(row['user_id']))
                mention = member.mention if member else f"@{row['username']}"
                
                active_mazeret = check_active_mazeret(self.bot.db, row['user_id'])
                mazeret_badge = " 💤" if active_mazeret else ""
                
                medals = {1: "🥇", 2: "🥈", 3: "🥉"}
                medal = medals.get(index, f"`#{index}`")
                leaderboard_text += f"{medal} {mention}{mazeret_badge} - **{formatted_time}**\n"
            
            embed.description = leaderboard_text
            embed.set_footer(text="San Andreas Highway Patrol • Otomatik Haftalık Kapanış")
            try:
                await channel.send(embed=embed)
            except Exception as e:
                logger.error(f"Failed to send weekly report embed to channel: {e}")
        else:
            logger.error(f"Weekly report channel {report_channel_id} not found.")

        try:
            weekly_officer_role = discord.utils.get(guild.roles, name="Haftanın Memuru")
            champion_id = int(totals[0]["user_id"]) if totals else None
            
            if weekly_officer_role:
                for member in weekly_officer_role.members:
                    if member.id != champion_id:
                        try:
                            await member.remove_roles(weekly_officer_role)
                            logger.info(f"Removed 'Haftanın Memuru' role from {member.name}")
                        except Exception as e:
                            logger.error(f"Failed to remove 'Haftanın Memuru' role from {member.name}: {e}")
                
                if champion_id:
                    champion_member = guild.get_member(champion_id)
                    if champion_member:
                        try:
                            await champion_member.add_roles(weekly_officer_role)
                            logger.info(f"Assigned 'Haftanın Memuru' role to {champion_member.name}")
                        except Exception as e:
                            logger.error(f"Failed to add 'Haftanın Memuru' role to {champion_member.name}: {e}")
            else:
                logger.warning("Role 'Haftanın Memuru' not found in guild. Role assignment skipped.")
        except Exception as e:
            logger.error(f"Error during role management in weekly report: {e}")

async def setup(bot):
    await bot.add_cog(MesaiCog(bot))
