import discord
from discord.ext import commands
import logging
import sys

# Force UTF-8 on Windows console to prevent emoji/unicode errors in log output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from config import Config
from analyzer import load_reference_images, reference_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)


class VerifyBot(commands.Bot):
    async def setup_hook(self):
        load_reference_images()
        log.info(f"References: {reference_summary()}")
        await self.load_extension("cogs.verify")
        await self.load_extension("cogs.admin")
        log.info("Cogs loaded.")


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = VerifyBot(command_prefix="!", intents=intents)

_synced = False

@bot.event
async def on_ready():
    global _synced
    log.info(f"Bot online: {bot.user} ({bot.user.id})")
    if not _synced:
        for guild in bot.guilds:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            log.info(f"Synced {len(synced)} command(s) to {guild.name}.")
        _synced = True
    log.info("Ready.")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")
    elif not isinstance(error, commands.CommandNotFound):
        log.error(f"Unhandled error: {error}")

if __name__ == "__main__":
    bot.run(Config.DISCORD_TOKEN)
