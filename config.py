import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Discord ───────────────────────────────────────────────────────────────
    DISCORD_TOKEN           = os.getenv("DISCORD_TOKEN")

    # Channel names — must match your Discord server exactly
    VERIFY_CHANNEL_NAME     = "𝙑𝙚𝙧𝙞𝙛𝙮-𝙎𝙨✅"   # channel where users submit screenshots
    LOG_CHANNEL_NAME        = "test"              # private staff log and command channel

    # Role names — must match your Discord server exactly
    KILLERS_ROLE_NAME       = "KILLers 🔥"
    MODERATOR_ROLE_NAMES    = ("Head Admin⚡", "Admins ✨")
    AUTHENTICATOR_ROLE_NAME = "Authenticator ✅"

    # Custom emoji name for the verified reaction (fallback: ✅)
    VERIFIED_REACTION_NAME  = "verified1"

    # ── Verification requirements ─────────────────────────────────────────────
    REQUIRED_TAG            = "[KILL]"   # clan tag that must appear in account name
    MIN_KD                  = 1.25       # minimum K/D ratio to pass
    MIN_GAMES_PLAYED        = 50         # minimum games played to be eligible
    MAX_PLAUSIBLE_KD        = 4.5        # K/D above this gets flagged for manual review

    # ── Rate limiting ─────────────────────────────────────────────────────────
    COOLDOWN_HOURS          = 0.025      # hours between resubmission attempts
    MAX_ATTEMPTS            = 7          # max attempts before locking user out

    # ── Gemini AI ─────────────────────────────────────────────────────────────
    GEMINI_API_KEY          = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL            = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
