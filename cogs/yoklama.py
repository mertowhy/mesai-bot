import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import logging
import datetime

logger = logging.getLogger("sahp_bot")

def build_yoklama_embed(guild, participants, date_str: str = None) -> discord.Embed:
    if not date_str:
        TR_TZ = datetime.timezone(datetime.timedelta(hours=3))
        date_str = datetime.datetime.now(TR_TZ).strftime("%d.%m.%Y")
        
    embed = discord.Embed(
        title=f"🚨 YOKLAMA — {date_str} 🚨",
        description=(
            "Bugün devriyeye çıkıp asayişi sağlayacak memurlarımıza ihtiyacımız var! Her birinizin katılımı ekibimizin gücünü gösterir.\n\n"
            "Aşağıdaki **Yoklamaya Katıl** butonunu kullanarak bugünkü rol katılımınızı bildirebilirsiniz!"
        ),
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    
    # Participant list formatting
    if participants:
        participant_lines = []
        for idx, p in enumerate(participants, 1):
            participant_lines.append(f"{idx}. <@{p['user_id']}>")
        participant_text = "\n".join(participant_lines)
    else:
        participant_text = "*Henüz yoklamaya katılan olmadı. İlk katılan sen ol! 👮*"
        
    embed.add_field(
        name="📋 BUGÜN ROLE GİRECEKLER:",
        value=participant_text,
        inline=False
    )
    
    embed.add_field(
        name="📊 Toplam Katılım",
        value=f"> **{len(participants)} memur aktif.**",
        inline=False
    )
    
    embed.set_footer(text="San Andreas Highway Patrol • Yoklama Sistemi")
    if guild and guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
        
    return embed

class YoklamaView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Yoklamaya Katıl", 
        style=discord.ButtonStyle.success, 
        emoji="🙋‍♂️", 
        custom_id="yoklama_katil"
    )
    async def katil(self, interaction: discord.Interaction, button: discord.ui.Button):
        message_id = str(interaction.message.id)
        user_id = str(interaction.user.id)
        username = interaction.user.display_name
        
        # Add to DB
        participants = self.bot.db.add_yoklama_participant(message_id, user_id, username)
        
        # Re-build and edit message
        # Extract date from embed title if possible, else generate new
        date_str = None
        if interaction.message.embeds:
            title = interaction.message.embeds[0].title
            # Title format: "🚨 SAHP GÜNLÜK YOKLAMA — DD.MM.YYYY 🚨"
            parts = title.split("—")
            if len(parts) > 1:
                date_str = parts[1].replace("🚨", "").strip()
                
        embed = build_yoklama_embed(interaction.guild, participants, date_str)
        await interaction.response.edit_message(embed=embed, view=self)
        
    @discord.ui.button(
        label="Yoklamadan Ayrıl", 
        style=discord.ButtonStyle.danger, 
        emoji="❌", 
        custom_id="yoklama_ayril"
    )
    async def ayril(self, interaction: discord.Interaction, button: discord.ui.Button):
        message_id = str(interaction.message.id)
        user_id = str(interaction.user.id)
        
        # Remove from DB
        participants = self.bot.db.remove_yoklama_participant(message_id, user_id)
        
        # Re-build and edit message
        date_str = None
        if interaction.message.embeds:
            title = interaction.message.embeds[0].title
            parts = title.split("—")
            if len(parts) > 1:
                date_str = parts[1].replace("🚨", "").strip()
                
        embed = build_yoklama_embed(interaction.guild, participants, date_str)
        await interaction.response.edit_message(embed=embed, view=self)

class YoklamaCog(commands.Cog, name="Yoklama İşlemleri"):
    def __init__(self, bot):
        self.bot = bot
        self.daily_yoklama_loop.start()

    def cog_unload(self):
        self.daily_yoklama_loop.cancel()

    TR_TZ = datetime.timezone(datetime.timedelta(hours=3))

    @tasks.loop(time=datetime.time(hour=17, minute=0, second=0, tzinfo=TR_TZ))
    async def daily_yoklama_loop(self):
        logger.info("Executing daily automatic yoklama loop...")
        
        # Get today's date string
        today_str = datetime.datetime.now(self.TR_TZ).strftime("%d.%m.%Y")
        
        # Check if yoklama already exists in DB for today
        existing = self.bot.db.get_yoklama_by_date(today_str)
        if existing:
            logger.info(f"Yoklama already sent/triggered for date {today_str}. Skipping automatic post.")
            return

        yoklama_channel_id = int(os.getenv("YOKLAMA_CHANNEL_ID", 1520765414777294938))
        
        guild_id = os.getenv("GUILD_ID")
        guild = self.bot.get_guild(int(guild_id)) if guild_id else None
        if not guild and self.bot.guilds:
            guild = self.bot.guilds[0]
            
        if not guild:
            logger.error("Could not find any guild to send daily yoklama.")
            return
            
        channel = guild.get_channel(yoklama_channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(yoklama_channel_id)
            except Exception as e:
                logger.error(f"Failed to fetch yoklama channel with ID {yoklama_channel_id}: {e}")
                return
                
        if channel:
            embed = build_yoklama_embed(guild, [], today_str)
            view = YoklamaView(self.bot)
            try:
                msg = await channel.send(content="@everyone", embed=embed, view=view)
                # Register in database to prevent double posts today
                self.bot.db.create_yoklama(str(msg.id), today_str)
                logger.info(f"Daily automatic yoklama message sent successfully. Msg ID: {msg.id}")
            except Exception as e:
                logger.error(f"Failed to send daily automatic yoklama message: {e}")
        else:
            logger.error(f"Yoklama channel {yoklama_channel_id} not found.")

    @daily_yoklama_loop.before_loop
    async def before_daily_yoklama_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="yoklamaal", description="Manuel olarak o günkü yoklama mesajını gönderir. (O gün bir daha otomatik atılmaz)")
    @app_commands.default_permissions(manage_guild=True)
    async def yoklamaal(self, interaction: discord.Interaction):
        # Prevent double trigger warning
        today_str = datetime.datetime.now(self.TR_TZ).strftime("%d.%m.%Y")
        existing = self.bot.db.get_yoklama_by_date(today_str)
        
        yoklama_channel_id = int(os.getenv("YOKLAMA_CHANNEL_ID", 1520765414777294938))
        channel = interaction.guild.get_channel(yoklama_channel_id)
        
        if not channel:
            try:
                channel = await self.bot.fetch_channel(yoklama_channel_id)
            except Exception:
                await interaction.response.send_message(
                    f"❌ Yoklama kanalı bulunamadı. Lütfen `.env` dosyasındaki `YOKLAMA_CHANNEL_ID` değerini kontrol edin.",
                    ephemeral=True
                )
                return
                
        if existing:
            logger.warning(f"Yoklama already exists for today ({today_str}). Posting a new one manually as requested.")

        embed = build_yoklama_embed(interaction.guild, [], today_str)
        view = YoklamaView(self.bot)
        
        try:
            msg = await channel.send(content="@everyone", embed=embed, view=view)
            # Create yoklama in DB for this message
            self.bot.db.create_yoklama(str(msg.id), today_str)
            
            status_msg = f"✅ Yoklama mesajı başarıyla {channel.mention} kanalında başlatıldı."
            if existing:
                status_msg += " (Not: Bugün için zaten bir yoklama alınmıştı, bu yeni mesajın butonları da aktif olacaktır.)"
            else:
                status_msg += " (Bu işlem sonucu bugün saat 17:00'daki otomatik yoklama iptal edilmiştir.)"
                
            await interaction.response.send_message(status_msg, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Yoklama mesajı gönderilirken hata oluştu: {e}",
                ephemeral=True
            )

async def setup(bot):
    cog = YoklamaCog(bot)
    await bot.add_cog(cog)
    bot.add_view(YoklamaView(bot))
