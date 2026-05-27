import sqlite3, logging, os
from datetime import datetime, timedelta
from config import Config

log = logging.getLogger(__name__)
DB_PATH = "data/verifications.db"


def _get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection

def _query(sql, params=()):
    with _get_connection() as connection:
        return connection.execute(sql, params).fetchall()

def _execute(sql, params=()):
    with _get_connection() as connection:
        cursor = connection.execute(sql, params)
        return cursor.rowcount


def init_db():
    with _get_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS verifications (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                username     TEXT NOT NULL,
                status       TEXT NOT NULL,
                kd           REAL,
                tag_found    INTEGER,
                tamper_score TEXT,
                tamper_reason TEXT,
                submitted_at TEXT NOT NULL,
                reviewed_by  TEXT
            );
            CREATE TABLE IF NOT EXISTS cooldowns (
                user_id       TEXT PRIMARY KEY,
                last_attempt  TEXT NOT NULL,
                attempt_count INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS verified_users (
                user_id     TEXT PRIMARY KEY,
                username    TEXT NOT NULL,
                verified_at TEXT NOT NULL,
                kd          REAL
            );
        """)
    log.info("Database initialised.")


# ── Cooldowns ─────────────────────────────────────────────────────────────────

def get_cooldown(user_id: str) -> dict | None:
    rows = _query("SELECT * FROM cooldowns WHERE user_id=?", (user_id,))
    return dict(rows[0]) if rows else None

def set_cooldown(user_id: str):
    now = datetime.utcnow().isoformat()
    with _get_connection() as connection:
        if connection.execute("SELECT 1 FROM cooldowns WHERE user_id=?", (user_id,)).fetchone():
            connection.execute(
                "UPDATE cooldowns SET last_attempt=?, attempt_count=attempt_count+1 WHERE user_id=?",
                (now, user_id)
            )
        else:
            connection.execute("INSERT INTO cooldowns VALUES (?,?,1)", (user_id, now))

def is_on_cooldown(user_id: str) -> tuple[bool, int]:
    cooldown_record = get_cooldown(user_id)
    if not cooldown_record:
        return False, 0
    last_attempt = datetime.fromisoformat(cooldown_record["last_attempt"])
    wait_duration = timedelta(hours=Config.COOLDOWN_HOURS)
    elapsed = datetime.utcnow() - last_attempt
    if elapsed < wait_duration:
        remaining_seconds = (wait_duration - elapsed).seconds
        return True, int(remaining_seconds / 3600) + 1
    return False, 0

def get_attempt_count(user_id: str) -> int:
    cooldown_record = get_cooldown(user_id)
    return cooldown_record["attempt_count"] if cooldown_record else 0

def reset_cooldown(user_id: str) -> int:
    return _execute("DELETE FROM cooldowns WHERE user_id=?", (user_id,))

def set_attempt_count(user_id: str, count: int):
    with _get_connection() as connection:
        connection.execute(
            """INSERT INTO cooldowns (user_id, last_attempt, attempt_count) VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET attempt_count=excluded.attempt_count""",
            (user_id, datetime.utcnow().isoformat(), count)
        )

def rollback_attempt(user_id: str):
    cooldown_record = get_cooldown(user_id)
    if not cooldown_record:
        return
    if cooldown_record["attempt_count"] <= 1:
        _execute("DELETE FROM cooldowns WHERE user_id=?", (user_id,))
    else:
        _execute("UPDATE cooldowns SET attempt_count=attempt_count-1 WHERE user_id=?", (user_id,))


# ── Verification log ──────────────────────────────────────────────────────────

def log_verification(user_id, username, status, kd=None, tag_found=None,
                     tamper_score=None, tamper_reason=None, reviewed_by=None):
    with _get_connection() as connection:
        connection.execute(
            """INSERT INTO verifications
               (user_id, username, status, kd, tag_found, tamper_score, tamper_reason, submitted_at, reviewed_by)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, username, status, kd, tag_found, tamper_score,
             tamper_reason, datetime.utcnow().isoformat(), reviewed_by)
        )

def mark_verified(user_id, username, kd):
    with _get_connection() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO verified_users VALUES (?,?,?,?)",
            (user_id, username, datetime.utcnow().isoformat(), kd)
        )

def unmark_verified(user_id: str) -> int:
    return _execute("DELETE FROM verified_users WHERE user_id=?", (user_id,))

def is_already_verified(user_id: str) -> bool:
    return bool(_query("SELECT 1 FROM verified_users WHERE user_id=?", (user_id,)))


# ── Queries ───────────────────────────────────────────────────────────────────

_TABLE_SQL = {
    "verifications":  "SELECT * FROM verifications ORDER BY submitted_at DESC",
    "cooldowns":      "SELECT * FROM cooldowns ORDER BY last_attempt DESC",
    "verified_users": "SELECT * FROM verified_users ORDER BY verified_at DESC",
}

def get_table_rows(table: str) -> list[dict]:
    if table not in _TABLE_SQL:
        raise ValueError(f"Unsupported table: {table}")
    return [dict(row) for row in _query(_TABLE_SQL[table])]

def get_all_verifications(limit=50) -> list[dict]:
    return [dict(row) for row in _query(
        "SELECT * FROM verifications ORDER BY submitted_at DESC LIMIT ?", (limit,))]

def get_verifications_for_user(user_id: str, limit=10) -> list[dict]:
    return [dict(row) for row in _query(
        "SELECT * FROM verifications WHERE user_id=? ORDER BY submitted_at DESC LIMIT ?",
        (user_id, limit))]

def get_verification(verification_id: int) -> dict | None:
    rows = _query("SELECT * FROM verifications WHERE id=?", (verification_id,))
    return dict(rows[0]) if rows else None

def get_db_counts() -> dict[str, int]:
    with _get_connection() as connection:
        return {
            table_name: connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            for table_name in _TABLE_SQL
        }


# ── Mutations ─────────────────────────────────────────────────────────────────

_ALLOWED_UPDATE = {"status", "kd", "tag_found", "tamper_score", "tamper_reason", "reviewed_by"}

def update_verification(verification_id: int, **fields) -> bool:
    updates = {key: value for key, value in fields.items() if key in _ALLOWED_UPDATE}
    if not updates:
        return False
    sql = f"UPDATE verifications SET {', '.join(f'{key}=?' for key in updates)} WHERE id=?"
    return _execute(sql, [*updates.values(), verification_id]) > 0

def delete_verification(verification_id: int) -> bool:
    return _execute("DELETE FROM verifications WHERE id=?", (verification_id,)) > 0

def delete_member_records(user_id: str, include_history=False) -> dict[str, int]:
    with _get_connection() as connection:
        verified_count       = connection.execute("DELETE FROM verified_users WHERE user_id=?",  (user_id,)).rowcount
        cooldown_count       = connection.execute("DELETE FROM cooldowns WHERE user_id=?",        (user_id,)).rowcount
        verifications_count  = connection.execute("DELETE FROM verifications WHERE user_id=?",    (user_id,)).rowcount if include_history else 0
    return {
        "verified_users": verified_count,
        "cooldowns":      cooldown_count,
        "verifications":  verifications_count,
    }
