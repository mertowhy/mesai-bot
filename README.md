# SAHP Mesai ve Mazeret Takip Botu

FiveM roleplay sunucularındaki SAHP (San Andreas Highway Patrol) departmanı için özel olarak tasarlanmış Discord botu.

## Özellikler

1. **Aktif Mesai Takibi:** 
   - Belirlenen ses kanalına giren memurların mesai süreleri saniye hassasiyetinde veritabanına kaydedilir.
   - Memurlar kanaldan ayrıldığında, o oturumda ne kadar süre kaldıklarını DM yoluyla alırlar.
   - `/mesai` komutu ile memurlar kendi toplam sürelerini görebilir.
   - `/mesai-sorgula` ile yetkililer memurların sürelerini görebilir.
   - `/mesai-liste` komutu ile sunucudaki en aktif memurlar listelenir (Liderlik tablosu).
   - `/mesai-temizle` komutu ile kayıtlar sıfırlanabilir.

2. **Mazeret Bildirim Sistemi:**
   - `/mazeret-kur` komutuyla belirlenen kanala kalıcı bir **Mazeret Bildir** butonu yerleştirilir.
   - Butona tıklayan memur; **Ad Soyad**, **Mazeret Süresi** ve **Mazeret Sebebi** girebileceği bir form (Modal) doldurur.
   - Form gönderildiğinde, talep sadece yetkililerin görebileceği `#gelen-mazeret` kanalına şık bir embed olarak iletilir.
   - Yetkililer mesajın altındaki **Onayla** veya **Reddet** butonlarına tıklayabilir. İşlem sonrasında memura DM aracılığıyla durum güncellemesi gönderilir.

## Kurulum ve Başlatma

1. **Sanal Ortamı Kurma ve Bağımlılıklar:**
   ```powershell
   python -m venv .venv
   .venv\Scripts\pip.exe install -r requirements.txt
   ```

2. **Yapılandırma:**
   - `.env` dosyasındaki alanları kendi sunucunuza ve botunuza göre düzenleyin (`DISCORD_TOKEN`, `AKTIF_MESAI_CHANNEL_ID` vb.).

3. **Botu Başlatma:**
   ```powershell
   .venv\Scripts\python.exe bot.py
   ```

Tüm detaylı ayarlar, kurulum adımları ve test yönergeleri için [walkthrough.md](file:///C:/Users/mertg/.gemini/antigravity-ide/brain/b9b5dfb0-7f86-4eda-9b1f-450bf83e0503/walkthrough.md) dosyasını inceleyebilirsiniz.
