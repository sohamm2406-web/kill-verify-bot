# pyrefly: ignore [missing-import]
import google.generativeai as genai
# pyrefly: ignore [missing-import]
import httpx, json, re, logging
from pathlib import Path
from dataclasses import dataclass
from config import Config

genai.configure(api_key=Config.GEMINI_API_KEY)
model = genai.GenerativeModel(Config.GEMINI_MODEL)
log = logging.getLogger(__name__)

REFERENCE_DIR = Path("reference_images")
_refs: dict[str, list[dict]] = {"legit": [], "tampered": []}
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def load_reference_images():
    for category in _refs:
        _refs[category].clear()
        folder = REFERENCE_DIR / category
        if not folder.exists():
            log.warning(f"Reference folder missing: {folder}")
            continue
        count = 0
        for image_path in sorted(folder.iterdir()):
            mime_type = _MIME.get(image_path.suffix.lower())
            if mime_type:
                try:
                    _refs[category].append({
                        "mime_type": mime_type,
                        "data":      image_path.read_bytes(),
                        "name":      image_path.name,
                    })
                    count += 1
                except Exception as error:
                    log.error(f"Could not load {image_path}: {error}")
        log.info(f"Loaded {count} {category} reference image(s).")


def reference_summary() -> str:
    return f"{len(_refs['legit'])} legit, {len(_refs['tampered'])} tampered reference image(s)"


# ── Prompt ────────────────────────────────────────────────────────────────────

_PROMPT = f"""You are a game stats screenshot verifier for clan {Config.REQUIRED_TAG}.

EXTRACT:
1. K/D ratio (exact number shown)
2. Account name — This is the player name whose stats are being shown in the game UI. It is usually next to 'Stats for...' or in the top-right profile corner.
3. Games played count
4. Visible kills and deaths

CRITICAL RULES FOR ACCOUNT NAME & CLAN TAG:
- The account name MUST be extracted ONLY from the actual game UI (e.g., the title "Stats for <Name>", or the profile box in the top-right).
- For the account name and "{Config.REQUIRED_TAG}" tag verification, DO NOT use text from browser tab titles, Windows taskbar/title bars, Discord window titles, or other open applications.
- The clan tag "{Config.REQUIRED_TAG}" MUST be part of the account name inside the game UI (e.g. "[KILL] PlayerName"). If the account name in the game UI does not contain "{Config.REQUIRED_TAG}", set "tag_found" to false.
- HOWEVER, you MUST still look at the entire image (including browser tabs, taskbars, and other open windows) for ANTI-TAMPER and cheat detection. For example, check for cheat programs, cheat sites, script executors, or mod search tabs.

ANTI-TAMPER — check all:
- Font/pixel consistency vs surrounding text (halos, smearing, bleed = flag)
- Background continuity behind numbers (patched/cloned = flag)
- Digit baseline alignment
- Statistical plausibility: K/D vs games/kills/deaths (K/D=8 with 30 games = suspicious)
- If kills+deaths visible: verify kills/deaths ≈ shown K/D; flag mismatches
- If wins/losses/matches/win-rate visible: verify they add up; flag contradictions
- UI element integrity (HUD matches game version)
- Color uniformity of stat numbers
- Screenshot source (photo-of-screen ok; photo-of-photo/design tool = flag)
- Script/cheat overlays: mod menus, ESP, aimbot UI, injected panels → set tamper_status="suspicious"

OUTPUT ONLY raw JSON (no markdown):
{{
  "kd": <number|null>,
  "tag_found": <bool>,
  "tag_account_name": "<full name or empty>",
  "games_played": <number|null>,
  "visible_kills": <number|null>,
  "visible_deaths": <number|null>,
  "stat_consistency": "<consistent|inconsistent|not_enough_info>",
  "tamper_status": "<clean|suspicious|tampered>",
  "tamper_reasons": ["<reason>"],
  "confidence": "<high|medium|low>",
  "notes": "<other observations>"
}}

Rules:
- clean → no suspicious signals
- suspicious → 1-2 minor signals (could be compression)
- tampered → clear editing evidence
- Stats mismatch → suspicious or tampered by severity
- Cheat overlay visible → suspicious + note in tamper_reasons
- confidence=low if blurry/cropped; high only if key fields clear + stats consistent
- Not a game stats screenshot at all → tampered + explain
"""


def _build_parts(user_image: dict) -> list:
    parts = [_PROMPT]
    for index, ref in enumerate(_refs["legit"], 1):
        parts += [
            f"\n--- LEGIT REFERENCE {index} (authentic font/UI/stats) ---\n",
            {"mime_type": ref["mime_type"], "data": ref["data"]},
        ]
    for index, ref in enumerate(_refs["tampered"], 1):
        parts += [
            f"\n--- TAMPERED REFERENCE {index} (edited — study artifacts/mismatches) ---\n",
            {"mime_type": ref["mime_type"], "data": ref["data"]},
        ]
    parts += ["\n--- SUBMISSION TO ANALYZE (compare against references above) ---\n", user_image]
    return parts


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class AnalysisResult:
    success: bool
    kd: float | None
    tag_found: bool
    tag_account_name: str
    games_played: int | None
    tamper_status: str        # clean | suspicious | tampered
    tamper_reasons: list[str]
    confidence: str           # high | medium | low
    raw_response: str
    notes: str = ""
    visible_kills: int | None = None
    visible_deaths: int | None = None
    stat_consistency: str = "not_enough_info"
    used_references: int = 0
    error: str | None = None


async def analyze_screenshot(image_url: str) -> AnalysisResult:
    try:
        async with httpx.AsyncClient(timeout=30) as http_client:
            http_response = await http_client.get(image_url)
            http_response.raise_for_status()
            user_image = {
                "mime_type": http_response.headers.get("content-type", "image/png").split(";")[0].strip(),
                "data":      http_response.content,
            }

        total_refs = len(_refs["legit"]) + len(_refs["tampered"])
        parts = _build_parts(user_image) if total_refs else [_PROMPT, user_image]
        log.info(f"Sending prompt with {total_refs} reference(s).")

        response = model.generate_content(parts)
        raw_response_text = response.text.strip()
        log.info(f"Gemini: {raw_response_text}")

        data = json.loads(
            re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_response_text, flags=re.MULTILINE).strip()
        )

        return AnalysisResult(
            success=True,
            kd=data.get("kd"),
            tag_found=bool(data.get("tag_found")),
            tag_account_name=data.get("tag_account_name", ""),
            games_played=data.get("games_played"),
            visible_kills=data.get("visible_kills"),
            visible_deaths=data.get("visible_deaths"),
            stat_consistency=data.get("stat_consistency", "not_enough_info"),
            tamper_status=data.get("tamper_status", "suspicious"),
            tamper_reasons=data.get("tamper_reasons", []),
            confidence=data.get("confidence", "low"),
            raw_response=raw_response_text,
            notes=data.get("notes", ""),
            used_references=total_refs,
        )

    except json.JSONDecodeError as error:
        log.error(f"JSON parse error: {error}\nRaw: {raw_response_text}")
        return AnalysisResult(False, None, False, "", None, "suspicious", [], "low", raw_response_text,
                              error="Could not parse AI response. Please resubmit.")
    except Exception as error:
        log.error(f"Gemini error ({Config.GEMINI_MODEL}): {error}")
        error_message = str(error)
        if "not found" in error_message and "models/" in error_message:
            error_message = f"Model '{Config.GEMINI_MODEL}' unavailable. Set GEMINI_MODEL=gemini-2.5-flash in .env."
        return AnalysisResult(False, None, False, "", None, "suspicious", [], "low", "", error=error_message)


# ── Verdict ───────────────────────────────────────────────────────────────────

_REVIEW_KW = ("script", "executor", "overlay", "mod menu", "cheat", "debug",
              "macro", "esp", "wallhack", "aimbot", "injected",
              "does not add up", "do not add up", "mismatch", "inconsistent", "contradiction")


def evaluate(result: AnalysisResult) -> tuple[str, list[str]]:
    """Returns (verdict, reasons). verdict: approved | rejected | flagged

    Stage 1: direct stat failures → always reject first.
    Stage 2: non-stat signals (tamper, confidence, high KD) → flag for review.
    """
    # ── Stage 1: direct stat failures → reject ───────────────────────────────
    rejection_reasons = []

    if not result.tag_found:
        rejection_reasons.append(f"{Config.REQUIRED_TAG} tag not found in account name")

    if result.kd is None:
        rejection_reasons.append("K/D ratio not visible in the screenshot")
    elif result.kd < Config.MIN_KD:
        rejection_reasons.append(f"K/D {result.kd:.2f} is below the minimum of {Config.MIN_KD}")

    if result.games_played is None:
        rejection_reasons.append("Games played count not visible in the screenshot")
    elif result.games_played < Config.MIN_GAMES_PLAYED:
        rejection_reasons.append(f"Only {result.games_played} games played — minimum is {Config.MIN_GAMES_PLAYED}")

    if rejection_reasons:
        return "rejected", rejection_reasons

    # ── Stage 2: non-stat signals → flag for review ──────────────────────────
    tamper_text = " ".join(result.tamper_reasons).lower()

    if any(keyword in tamper_text for keyword in _REVIEW_KW):
        return "flagged", result.tamper_reasons or ["Submission needs staff review"]

    if result.tamper_status in ("tampered", "suspicious"):
        return "flagged", result.tamper_reasons or ["Image flagged for staff review"]

    if result.confidence == "low":
        return "flagged", ["Screenshot too blurry/cropped — could not read stats reliably"]

    if result.kd > Config.MAX_PLAUSIBLE_KD:
        return "flagged", [f"K/D of {result.kd} is unusually high — needs staff verification"]

    return "approved", []
