import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import sys
import time
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from database import Database

# Web server for Render health checks
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        # Suppress request logging to keep console clean
        return

def run_health_check_server():
    port = int(os.getenv("PORT", 8080))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        logging.getLogger("sahp_bot").info(f"Render health check server started on port {port}")
        server.serve_forever()
    except Exception as e:
        logging.getLogger("sahp_bot").error(f"Failed to start health check server: {e}")

# Load environment variables
load_dotenv()

# Configure Logging
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)

logging.basicConfig(
    level=log_level,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger("sahp_bot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID") # Optional for fast command syncing

if not DISCORD_TOKEN or DISCORD_TOKEN == "your_discord_bot_token_here":
    logger.critical("DISCORD_TOKEN is missing or not configured in .env file.")
    sys.exit(1)

class SAHPBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.voice_states = True
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        # Initialize database
        self.db = Database(os.getenv("MONGO_URI"))

    async def setup_hook(self):
        # Load extensions
        cogs = ["cogs.mesai", "cogs.mazeret", "cogs.yoklama"]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"Extension {cog} loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load extension {cog}: {e}")

        # Command syncing
        try:
            if GUILD_ID:
                # Sync to test/server guild immediately
                guild = discord.Object(id=int(GUILD_ID))
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info(f"Slash commands synced to guild {GUILD_ID}.")
            else:
                # Sync globally (takes up to 1 hour to propagate)
                await self.tree.sync()
                logger.info("Slash commands synced globally.")
        except discord.Forbidden as e:
            logger.error(f"Failed to sync slash commands due to permission issues (Missing Access): {e}")
            logger.warning("Make sure the bot is invited with 'applications.commands' scope, and GUILD_ID in your env is correct and belongs to a server the bot is in.")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

    async def on_ready(self):
        logger.info(f"Bot connected successfully as {self.user} (ID: {self.user.id})")
        
        # Log loaded configurations for troubleshooting
        logger.info("--- Sunucu Yapılandırma Bilgileri ---")
        logger.info(f"AKTIF_MESAI_CHANNEL_ID: {os.getenv('AKTIF_MESAI_CHANNEL_ID')}")
        logger.info(f"MESAI_LOG_CHANNEL_ID: {os.getenv('MESAI_LOG_CHANNEL_ID')}")
        logger.info(f"MAZERET_CHANNEL_ID: {os.getenv('MAZERET_CHANNEL_ID')}")
        logger.info(f"GELEN_MAZERET_CHANNEL_ID: {os.getenv('GELEN_MAZERET_CHANNEL_ID')}")
        logger.info(f"GUILD_ID: {os.getenv('GUILD_ID')}")
        logger.info(f"LOG_LEVEL: {os.getenv('LOG_LEVEL')}")
        logger.info("-------------------------------------")
        # 1. Clear active sessions that were left open due to bot crash/restart
        current_time = int(time.time())
        self.db.clear_active_sessions(current_time)
        
        # 2. Check current voice channel state and start sessions for members in the channel
        aktif_mesai_id = os.getenv("AKTIF_MESAI_CHANNEL_ID")
        if aktif_mesai_id:
            try:
                channel_id = int(aktif_mesai_id)
                channel = self.get_channel(channel_id)
                if not channel:
                    channel = await self.fetch_channel(channel_id)
                
                if channel and isinstance(channel, discord.VoiceChannel):
                    for member in channel.members:
                        if not member.bot:
                            self.db.start_session(str(member.id), member.display_name, current_time)
                    logger.info(f"Scanned voice channel {channel.name}. Active sessions started.")
            except ValueError:
                logger.error("AKTIF_MESAI_CHANNEL_ID in .env is not a valid number.")
            except Exception as e:
                logger.error(f"Error during voice channel scan on startup: {e}")

    async def close(self):
        logger.info("Shutting down bot. Closing database...")
        self.db.close()
        await super().close()

# Prefix command for manual syncing by owner
bot = SAHPBot()

@bot.command(name="sync")
@commands.is_owner()
async def manual_sync(ctx):
    await bot.tree.sync()
    await ctx.send("Slash commands have been synced globally!")

if __name__ == "__main__":
    # Start health check server in a daemon thread for Render compatibility
    threading.Thread(target=run_health_check_server, daemon=True).start()
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.critical("Invalid Discord Token provided. Please check your .env configuration.")
    except Exception as e:
        logger.critical(f"Bot crashed during run: {e}")
