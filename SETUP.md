# KILL Clan Verification Bot — Setup Guide

## What this bot does

- Watches `#Verify-Ss` for screenshots submitted by members
- Sends the image to Google Gemini AI for analysis
- Checks: K/D ratio, `[KILL]` tag in account name, games played, and image authenticity
- **Auto-approves** (assigns `KILLers` role) if all requirements are met and the image looks clean
- **Auto-rejects** if a required stat is missing or below the minimum
- **Flags for manual review** (with Approve/Reject buttons) if tampering signals are detected
- Logs every submission to the staff channel for full audit history

---

## 1. Create the Discord Bot

1. Go to https://discord.com/developers/applications → New Application → name it
2. Left sidebar → **Bot** → Add Bot → copy the **Token** → save it
3. Under **Privileged Gateway Intents** enable:
   - **SERVER MEMBERS INTENT**
   - **MESSAGE CONTENT INTENT**
4. Left sidebar → **OAuth2 → URL Generator**
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: `Manage Roles`, `Send Messages`, `Read Message History`,
     `Attach Files`, `Embed Links`, `Manage Messages`, `Add Reactions`
5. Copy the generated URL, open it in your browser, and invite the bot to your server

---

## 2. Get a Free Gemini API Key

1. Go to https://aistudio.google.com/app/apikey
2. Sign in with Google → **Create API key**
3. Copy the key — free tier allows 1,500 requests/day (more than enough)

---

## 3. Set Up Your Discord Server

### Channels
Create these exact channel names (or update `config.py` to match yours):

| Channel | Purpose |
|---|---|
| `𝙑𝙚𝙧𝙞𝙛𝙮-𝙎𝙨✅` | Public — members submit screenshots here |
| `test` | Private staff — logs, decisions, slash commands |

### Roles
- Create a role named exactly `KILLers 🔥` (or update `KILLERS_ROLE_NAME` in `config.py`)
- Create a role named exactly `Authenticator ✅` (or update `AUTHENTICATOR_ROLE_NAME`)
- **Important:** The bot's role must be placed **above** the `KILLers` role in Server Settings → Roles

---

## 4. Local Setup

```bash
# Navigate to the project folder
cd kill-verify-bot

# Create a virtual environment
python -m venv venv

# Activate it
# Windows (Command Prompt):  venv\Scripts\python.exe bot.py
# Windows (PowerShell):      Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
#                            then: venv\Scripts\activate
# macOS / Linux:             source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create your .env file
cp .env.example .env
# Open .env and fill in your DISCORD_TOKEN and GEMINI_API_KEY

# Run the bot
python bot.py
```

---

## 5. Adjust Requirements (config.py)

```python
REQUIRED_TAG         = "[KILL]"   # clan tag that must appear in the account name
MIN_KD               = 1.25       # minimum K/D ratio required
MIN_GAMES_PLAYED     = 50         # minimum games played
MAX_PLAUSIBLE_KD     = 4.5        # K/D above this is flagged for manual review
COOLDOWN_HOURS       = 0.025      # hours between resubmission attempts (~1.5 min)
MAX_ATTEMPTS         = 7          # max submission attempts before locking user out
```

---

## 6. Adding Reference Images (optional but recommended)

Place reference screenshots in the following folders to help Gemini detect tampering:

```
reference_images/
├── legit/       ← genuine unedited stats screenshots
└── tampered/    ← edited or suspicious screenshots
```

- Supported formats: `.png`, `.jpg`, `.jpeg`, `.webp`
- More references = better tamper detection accuracy
- Reload without restarting using `/reloadrefs` in the staff channel

---

## 7. Free Hosting (pick one)

### Option A — Railway (easiest, 500 free hours/month)
1. Push your code to a **private** GitHub repo (`.env` is already in `.gitignore`)
2. Go to https://railway.app → New Project → Deploy from GitHub
3. Add environment variables: `DISCORD_TOKEN`, `GEMINI_API_KEY`
4. It auto-detects Python and runs `python bot.py`

### Option B — Render (750 free hours/month)
1. Push to GitHub
2. Go to https://render.com → New → **Background Worker**
3. Build command: `pip install -r requirements.txt`
4. Start command: `python bot.py`
5. Add environment variables in the dashboard

### Option C — Run locally 24/7
- A Raspberry Pi, old laptop, or always-on PC works fine
- Use `screen`, `tmux`, or `pm2` to keep the process running after closing the terminal

---

## 8. Staff Commands

All slash commands must be used inside the configured staff log channel (`#test` by default):

| Command | Description |
|---|---|
| `/verifystatus <member>` | Check a member's verification status, attempts, and history |
| `/recentverify [limit]` | Show recent verification attempts |
| `/reloadrefs` | Reload reference images from disk without restarting |
| `/db user <member>` | Show all DB records for a specific member |
| `/db all [table]` | Show the full database (or a specific table) |
| `/db verify <member>` | Manually mark a member as verified and assign role |
| `/db unverify <member>` | Remove a member from verified users |
| `/db resetcd <member>` | Reset a member's cooldown |
| `/db attempts <member> <count>` | Set a member's attempt count |
| `/db update <id>` | Edit a verification record by ID |
| `/db delete <id>` | Delete a verification record by ID |
| `/db delete-member <member>` | Delete all DB records for a member |

---

## 9. How Verdicts Work

| Verdict | Condition | Action |
|---|---|---|
| **Approved** | Tag found, K/D ≥ min, games ≥ min, no tamper signals | Role assigned automatically |
| **Rejected** | Tag missing, K/D below min, games below min, or stat not visible | Clear rejection message with reason |
| **Flagged** | Stats pass but tamper/cheat signals detected or K/D unusually high | Concise public message + Approve/Reject buttons for staff |
| **Invalid** | Screenshot is not a stats page at all | Rejection with step-by-step instructions |

---

## 10. Troubleshooting

**Bot doesn't respond in the verify channel:**
→ Make sure MESSAGE CONTENT INTENT is enabled in the Discord Developer Portal

**Role not being assigned after approval:**
→ The bot's role must be above the `KILLers` role in Server Settings → Roles

**Gemini quota errors:**
→ You've hit the 1,500/day free limit. Check https://aistudio.google.com for usage. Paid tiers available.

**"Could not parse AI response":**
→ Gemini occasionally wraps JSON in markdown. The bot strips this automatically, but if it persists, check `bot.log` for the raw response.

**Windows PowerShell activation error:**
→ Run `python bot.py` directly via `venv\Scripts\python.exe bot.py` — no activation needed.
