import discord
from discord import app_commands
from discord.ext import commands
import os
import logging
import re
import datetime

logger = logging.getLogger("sahp_bot")

class MazeretRejectModal(discord.ui.Modal):
    def __init__(self, message: discord.Message, view: discord.ui.View):
        super().__init__(title="Mazeret Red Gerekçesi")
        self.message = message
        self.view = view

        self.reason = discord.ui.TextInput(
            label="Red Sebebi",
            style=discord.TextStyle.long,
            placeholder="Mazeretin reddedilme gerekçesini yazınız...",
            required=True,
            max_length=500
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        embed = self.message.embeds[0]
        embed.color = discord.Color.red()
        
        status_field_exists = False
        for i, field in enumerate(embed.fields):
            if field.name == "Durum":
                status_field_exists = True
                embed.set_field_at(i, name="Durum", value=f"❌ Reddedildi (Reddeden: {interaction.user.mention})", inline=False)
                break
        
        if not status_field_exists:
            embed.add_field(name="Durum", value=f"❌ Reddedildi (Reddeden: {interaction.user.mention})", inline=False)

        # Add red sebebi to embed
        embed.add_field(name="Red Sebebi", value=self.reason.value, inline=False)

        # Disable buttons
        for child in self.view.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self.view)
        
        # Notify the member in DMs
        try:
            member_id = None
            for field in embed.fields:
                if field.name == "Memur":
                    clean_mention = field.value.split(" ")[0]
                    member_id = int(clean_mention.replace("<@", "").replace(">", ""))
                    break
            if member_id:
                member = interaction.guild.get_member(member_id)
                if member:
                    dm_embed = discord.Embed(
                        title="Mazeret Talebi Güncellemesi",
                        description=f"Gönderdiğiniz mazeret talebi reddedilmiştir.\n\n**Reddeden:** {interaction.user.display_name}\n**Red Sebebi:** {self.reason.value}",
                        color=discord.Color.red()
                    )
                    dm_embed.set_footer(text="San Andreas Highway Patrol")
                    await member.send(embed=dm_embed)
        except Exception as e:
            logger.warning(f"Could not send rejection DM: {e}")

class MazeretReviewView(discord.ui.View):
    def __init__(self):
        # We set timeout=None to make this view persistent as well
        super().__init__(timeout=None)

    @discord.ui.button(label="Onayla", style=discord.ButtonStyle.success, emoji="✅", custom_id="mazeret_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Allow administrators or members with '.' role to review
        has_permission = interaction.user.guild_permissions.administrator
        if not has_permission:
            # Check for role named '.'
            for role in interaction.user.roles:
                if role.name == ".":
                    has_permission = True
                    break

        if not has_permission:
            await interaction.response.send_message("❌ Bu işlemi gerçekleştirmek için yetkiniz bulunmamaktadır.", ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        # Change color to green and append approval info
        embed.color = discord.Color.green()
        
        # Check if status field already exists to prevent duplicate updates
        status_field_exists = False
        for i, field in enumerate(embed.fields):
            if field.name == "Durum":
                status_field_exists = True
                embed.set_field_at(i, name="Durum", value=f"✅ Onaylandı (Onaylayan: {interaction.user.mention})", inline=False)
                break
        
        if not status_field_exists:
            embed.add_field(name="Durum", value=f"✅ Onaylandı (Onaylayan: {interaction.user.mention})", inline=False)

        # Disable buttons
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)
        
        # Save approved mazeret to MongoDB
        try:
            member_id = None
            username = ""
            dates = ""
            reason = ""
            for field in embed.fields:
                if field.name == "Memur":
                    clean_mention = field.value.split(" ")[0]
                    member_id = int(clean_mention.replace("<@", "").replace(">", ""))
                elif field.name == "Ad Soyad / Rozet":
                    username = field.value
                elif field.name == "Mazeret Süresi":
                    dates = field.value
                elif field.name == "Mazeret Sebebi":
                    reason = field.value
            
            if member_id:
                member = interaction.guild.get_member(member_id)
                member_display_name = member.display_name if member else username
                db = interaction.client.db
                db.add_approved_mazeret(
                    str(member_id),
                    member_display_name,
                    dates,
                    reason,
                    interaction.user.display_name
                )
        except Exception as e:
            logger.error(f"Error saving approved mazeret to database: {e}")
            
        # Optionally, notify the member in DMs
        try:
            member_id = None
            for field in embed.fields:
                if field.name == "Memur":
                    # Extract ID from mention e.g., <@123456> -> 123456
                    clean_mention = field.value.split(" ")[0]
                    member_id = int(clean_mention.replace("<@", "").replace(">", ""))
                    break
            if member_id:
                member = interaction.guild.get_member(member_id)
                if member:
                    dm_embed = discord.Embed(
                        title="Mazeret Talebi Güncellemesi",
                        description=f"Gönderdiğiniz mazeret talebi onaylanmıştır.\n\n**Onaylayan:** {interaction.user.display_name}",
                        color=discord.Color.green()
                    )
                    dm_embed.set_footer(text="San Andreas Highway Patrol")
                    await member.send(embed=dm_embed)
        except Exception as e:
            logger.warning(f"Could not send approval DM: {e}")

    @discord.ui.button(label="Reddet", style=discord.ButtonStyle.danger, emoji="❌", custom_id="mazeret_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Allow administrators or members with '.' role to review
        has_permission = interaction.user.guild_permissions.administrator
        if not has_permission:
            # Check for role named '.'
            for role in interaction.user.roles:
                if role.name == ".":
                    has_permission = True
                    break

        if not has_permission:
            await interaction.response.send_message("❌ Bu işlemi gerçekleştirmek için yetkiniz bulunmamaktadır.", ephemeral=True)
            return

        # Open the rejection reason modal
        await interaction.response.send_modal(MazeretRejectModal(interaction.message, self))

class MazeretModal(discord.ui.Modal):
    def __init__(self, bot):
        super().__init__(title="SAHP Mazeret Bildirim Formu")
        self.bot = bot

        self.isim_rozet = discord.ui.TextInput(
            label="Ad Soyad ve Rozet Numarası",
            placeholder="Örn: John Doe - 105",
            required=True,
            max_length=50
        )
        self.tarih = discord.ui.TextInput(
            label="Mazeret Süresi (Gün veya Tarih)",
            placeholder="Örn: 2 gün veya 27.06.2026 - 30.06.2026",
            required=True,
            max_length=100
        )
        self.neden = discord.ui.TextInput(
            label="Mazeret Sebebi",
            style=discord.TextStyle.long,
            placeholder="Mazeretinizin gerekçesini açıklayın...",
            required=True,
            max_length=1000
        )

        self.add_item(self.isim_rozet)
        self.add_item(self.tarih)
        self.add_item(self.neden)

    async def on_submit(self, interaction: discord.Interaction):
        gelen_mazeret_id = int(os.getenv("GELEN_MAZERET_CHANNEL_ID", 0))
        channel = interaction.guild.get_channel(gelen_mazeret_id)

        if not channel:
            await interaction.response.send_message(
                "❌ Gelen mazeret kanalı bulunamadı. Lütfen bot yöneticisi ile iletişime geçin.", 
                ephemeral=True
            )
            return

        # Process the duration/day input
        tarih_degeri = self.tarih.value.strip()
        
        # Check if user entered "X gün", "X gun" or just a number "X"
        match = re.match(r'^(\d+)\s*(?:gün|gun)?$', tarih_degeri.lower())
        if match:
            try:
                days = int(match.group(1))
                now = datetime.datetime.now()
                start_str = now.strftime("%d.%m.%Y")
                end_dt = now + datetime.timedelta(days=days)
                end_str = end_dt.strftime("%d.%m.%Y")
                tarih_degeri = f"{start_str} - {end_str}"
            except Exception:
                pass

        # Prepare review embed
        embed = discord.Embed(
            title="📝 Yeni Mazeret Bildirimi",
            color=discord.Color.orange(),
            timestamp=interaction.created_at
        )
        embed.add_field(name="Memur", value=f"{interaction.user.mention} ({interaction.user.id})", inline=True)
        embed.add_field(name="Ad Soyad / Rozet", value=self.isim_rozet.value, inline=True)
        embed.add_field(name="Mazeret Süresi", value=tarih_degeri, inline=False)
        embed.add_field(name="Mazeret Sebebi", value=self.neden.value, inline=False)
        embed.set_footer(text="San Andreas Highway Patrol Mazeret Sistemi")
        if interaction.user.display_avatar:
            embed.set_thumbnail(url=interaction.user.display_avatar.url)

        # Send to gelen-mazeret with the review buttons view
        view = MazeretReviewView()
        await channel.send(embed=embed, view=view)

        await interaction.response.send_message(
            "✅ Mazeret talebiniz başarıyla iletildi. Yetkililer inceledikten sonra bilgilendirileceksiniz.", 
            ephemeral=True
        )

class MazeretView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Mazeret Bildir", 
        style=discord.ButtonStyle.danger, 
        emoji="📝", 
        custom_id="mazeret_submit_button"
    )
    async def mazeret_bildir(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MazeretModal(self.bot))

class MazeretCog(commands.Cog, name="Mazeret İşlemleri"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mazeret-kur", description="Mazeret bildirme butonunun yer aldığı embed mesajı kurar.")
    @app_commands.default_permissions(manage_guild=True)
    async def mazeret_kur(self, interaction: discord.Interaction):
        mazeret_channel_id = int(os.getenv("MAZERET_CHANNEL_ID", 0))
        channel = interaction.guild.get_channel(mazeret_channel_id)

        if not channel:
            await interaction.response.send_message(
                f"❌ `.env` dosyasında yapılandırılan `#mazeret` kanalı (ID: {mazeret_channel_id}) sunucuda bulunamadı.", 
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🚔 SAHP Mazeret Bildirim Sistemi",
            description=(
                "Toplantılara katılamayacağınız, aktif devriye atamayacağınız veya "
                "belirli tarihler arasında mesaiye katılım sağlayamayacağınız durumlarda "
                "aşağıdaki **Mazeret Bildir** butonuna tıklayarak mazeretinizi iletebilirsiniz.\n\n"
                "⚠️ *Mazeretinizin geçerli sayılması için detaylı açıklama yazılması zorunludur.*"
            ),
            color=discord.Color.blue()
        )
        embed.set_footer(text="San Andreas Highway Patrol • Command Staff")
        
        # Send view
        view = MazeretView(self.bot)
        await channel.send(embed=embed, view=view)
        
        await interaction.response.send_message(
            f"✅ Mazeret bildirim paneli {channel.mention} kanalına başarıyla kuruldu.", 
            ephemeral=True
        )

    @app_commands.command(name="mazeret-bitir", description="Aktif mazeretinizi sonlandırır.")
    @app_commands.describe(kullanici="Mazereti sonlandırılacak memur (Sadece Yetkililer)")
    async def mazeret_bitir(self, interaction: discord.Interaction, kullanici: discord.Member = None):
        target_member = kullanici or interaction.user
        
        # Permission check if target is someone else
        if target_member != interaction.user:
            has_permission = interaction.user.guild_permissions.administrator
            if not has_permission:
                for role in interaction.user.roles:
                    if role.name == ".":
                        has_permission = True
                        break
            if not has_permission:
                await interaction.response.send_message(
                    "❌ Başka bir memurun mazeretini sonlandırmak için yetkiniz bulunmamaktadır.", 
                    ephemeral=True
                )
                return

        # Check if the target member has an active mazeret
        active_mazeret = self.bot.db.get_current_active_mazeret(str(target_member.id))
        
        if not active_mazeret:
            if target_member == interaction.user:
                await interaction.response.send_message(
                    "❌ Aktif bir mazeretiniz bulunmamaktadır.", 
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"❌ {target_member.mention} adlı memurun aktif bir mazereti bulunmamaktadır.", 
                    ephemeral=True
                )
            return

        # End the mazeret
        success = self.bot.db.end_mazeret(active_mazeret["_id"])
        if success:
            if target_member == interaction.user:
                await interaction.response.send_message(
                    "✅ Aktif mazeretiniz başarıyla sonlandırıldı.", 
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"✅ {target_member.mention} adlı memurun aktif mazereti başarıyla sonlandırıldı.", 
                    ephemeral=True
                )
        else:
            await interaction.response.send_message(
                "❌ Mazeret sonlandırılırken veritabanı hatası oluştu.", 
                ephemeral=True
            )

async def setup(bot):
    cog = MazeretCog(bot)
    await bot.add_cog(cog)
    # Register the persistent views in the bot
    bot.add_view(MazeretView(bot))
    bot.add_view(MazeretReviewView())
