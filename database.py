import sqlite3
from datetime import date, timedelta

DB_PATH = "wizari.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id      INTEGER PRIMARY KEY,
            name         TEXT,
            xp           INTEGER DEFAULT 0,
            streak       INTEGER DEFAULT 0,
            last_date    TEXT,
            total_games  INTEGER DEFAULT 0,
            reminders_on INTEGER DEFAULT 0,
            reminder_time TEXT DEFAULT '20:00'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS subject_stats (
            user_id  INTEGER,
            subject  TEXT,
            games    INTEGER DEFAULT 0,
            correct  INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, subject)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS challenges (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            challenger        INTEGER,
            opponent          INTEGER,
            subject           TEXT,
            status            TEXT DEFAULT 'pending',
            challenger_score  INTEGER DEFAULT -1,
            opponent_score    INTEGER DEFAULT -1,
            created_at        TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS weekly_stats (
            user_id  INTEGER,
            week     TEXT,
            games    INTEGER DEFAULT 0,
            correct  INTEGER DEFAULT 0,
            xp       INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, week)
        )
    """)

    # Group session table
    c.execute("""
        CREATE TABLE IF NOT EXISTS group_sessions (
            session_id   TEXT PRIMARY KEY,
            owner_id     INTEGER,
            owner_name   TEXT,
            subject      TEXT,
            status       TEXT DEFAULT 'waiting',
            chat_id      INTEGER,
            msg_id       INTEGER,
            created_at   TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS session_players (
            session_id  TEXT,
            user_id     INTEGER,
            user_name   TEXT,
            score       INTEGER DEFAULT 0,
            finished    INTEGER DEFAULT 0,
            PRIMARY KEY (session_id, user_id)
        )
    """)

    conn.commit()
    conn.close()

# ── User functions ──────────────────────────────────────────

def register_user(user_id: int, name: str):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO users (user_id, name) VALUES (?, ?)", (user_id, name))
    conn.execute("UPDATE users SET name=? WHERE user_id=?", (name, user_id))
    conn.commit()
    conn.close()

def get_user_stats(user_id: int) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return {"xp": 0, "streak": 0, "total_games": 0, "reminders_on": 0, "reminder_time": "20:00"}
    return dict(row)

def update_stats(user_id: int, earned_xp: int, correct: int, total: int, subject: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        conn.close()
        return

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    last_date = row["last_date"]
    streak = row["streak"]

    if last_date == today:
        pass
    elif last_date == yesterday:
        streak += 1
    else:
        streak = 1

    conn.execute(
        "UPDATE users SET xp=xp+?, streak=?, last_date=?, total_games=total_games+1 WHERE user_id=?",
        (earned_xp, streak, today, user_id)
    )
    conn.execute("INSERT OR IGNORE INTO subject_stats (user_id, subject) VALUES (?, ?)", (user_id, subject))
    conn.execute(
        "UPDATE subject_stats SET games=games+1, correct=correct+? WHERE user_id=? AND subject=?",
        (correct, user_id, subject)
    )

    week = date.today().strftime("%Y-W%W")
    conn.execute("INSERT OR IGNORE INTO weekly_stats (user_id, week) VALUES (?, ?)", (user_id, week))
    conn.execute(
        "UPDATE weekly_stats SET games=games+1, correct=correct+?, xp=xp+? WHERE user_id=? AND week=?",
        (correct, earned_xp, user_id, week)
    )

    conn.commit()
    conn.close()

def get_leaderboard(limit: int = 10) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT name, xp, streak FROM users ORDER BY xp DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_subject_stats(user_id: int) -> dict:
    conn = get_conn()
    rows = conn.execute(
        "SELECT subject, games, correct FROM subject_stats WHERE user_id=?", (user_id,)
    ).fetchall()
    conn.close()
    return {r["subject"]: dict(r) for r in rows}

def get_weekly_report(user_id: int) -> dict:
    conn = get_conn()
    week = date.today().strftime("%Y-W%W")
    row = conn.execute(
        "SELECT * FROM weekly_stats WHERE user_id=? AND week=?", (user_id, week)
    ).fetchone()
    conn.close()
    return dict(row) if row else {"games": 0, "correct": 0, "xp": 0}

def set_reminder(user_id: int, on: bool, time_str: str = "20:00"):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET reminders_on=?, reminder_time=? WHERE user_id=?",
        (1 if on else 0, time_str, user_id)
    )
    conn.commit()
    conn.close()

def get_reminder_users() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT user_id, name, reminder_time FROM users WHERE reminders_on=1"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_by_username_search(name: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT user_id, name FROM users WHERE name LIKE ? LIMIT 5", (f"%{name}%",)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Challenge functions ─────────────────────────────────────

def create_challenge(challenger: int, opponent: int, subject: str) -> int:
    conn = get_conn()
    today = date.today().isoformat()
    cur = conn.execute(
        "INSERT INTO challenges (challenger, opponent, subject, created_at) VALUES (?, ?, ?, ?)",
        (challenger, opponent, subject, today)
    )
    challenge_id = cur.lastrowid
    conn.commit()
    conn.close()
    return challenge_id

def get_challenge(challenge_id: int) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_challenge_score(challenge_id: int, is_challenger: bool, score: int):
    conn = get_conn()
    field = "challenger_score" if is_challenger else "opponent_score"
    conn.execute(f"UPDATE challenges SET {field}=? WHERE id=?", (score, challenge_id))
    row = conn.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
    if row and row["challenger_score"] >= 0 and row["opponent_score"] >= 0:
        conn.execute("UPDATE challenges SET status='finished' WHERE id=?", (challenge_id,))
    conn.commit()
    conn.close()

def get_pending_challenge(user_id: int) -> dict:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM challenges WHERE opponent=? AND status='pending'", (user_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

# ── Group Session functions ─────────────────────────────────

def create_session(session_id: str, owner_id: int, owner_name: str, subject: str, chat_id: int) -> None:
    conn = get_conn()
    today = date.today().isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO group_sessions (session_id, owner_id, owner_name, subject, chat_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, owner_id, owner_name, subject, chat_id, today)
    )
    # Add owner as first player
    conn.execute(
        "INSERT OR IGNORE INTO session_players (session_id, user_id, user_name) VALUES (?, ?, ?)",
        (session_id, owner_id, owner_name)
    )
    conn.commit()
    conn.close()

def get_session(session_id: str) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM group_sessions WHERE session_id=?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def join_session(session_id: str, user_id: int, user_name: str) -> bool:
    """Returns False if session full or already started"""
    conn = get_conn()
    count = conn.execute(
        "SELECT COUNT(*) as c FROM session_players WHERE session_id=?", (session_id,)
    ).fetchone()["c"]
    session = conn.execute(
        "SELECT status FROM group_sessions WHERE session_id=?", (session_id,)
    ).fetchone()

    if not session or session["status"] != "waiting" or count >= 25:
        conn.close()
        return False

    conn.execute(
        "INSERT OR IGNORE INTO session_players (session_id, user_id, user_name) VALUES (?, ?, ?)",
        (session_id, user_id, user_name)
    )
    conn.commit()
    conn.close()
    return True

def get_session_players(session_id: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM session_players WHERE session_id=? ORDER BY score DESC",
        (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def start_session(session_id: str):
    conn = get_conn()
    conn.execute("UPDATE group_sessions SET status='active' WHERE session_id=?", (session_id,))
    conn.commit()
    conn.close()

def update_session_score(session_id: str, user_id: int, score: int):
    conn = get_conn()
    conn.execute(
        "UPDATE session_players SET score=?, finished=1 WHERE session_id=? AND user_id=?",
        (score, session_id, user_id)
    )
    conn.commit()
    conn.close()

def finish_session(session_id: str):
    conn = get_conn()
    conn.execute("UPDATE group_sessions SET status='finished' WHERE session_id=?", (session_id,))
    conn.commit()
    conn.close()

def set_session_msg(session_id: str, msg_id: int):
    conn = get_conn()
    conn.execute("UPDATE group_sessions SET msg_id=? WHERE session_id=?", (msg_id, session_id))
    conn.commit()
    conn.close()

def get_finished_count(session_id: str) -> tuple:
    conn = get_conn()
    total = conn.execute(
        "SELECT COUNT(*) as c FROM session_players WHERE session_id=?", (session_id,)
    ).fetchone()["c"]
    finished = conn.execute(
        "SELECT COUNT(*) as c FROM session_players WHERE session_id=? AND finished=1", (session_id,)
    ).fetchone()["c"]
    conn.close()
    return finished, total

def cleanup_old_sessions():
    conn = get_conn()
    conn.execute("DELETE FROM group_sessions WHERE status='waiting' AND created_at < date('now', '-1 day')")
    conn.commit()
    conn.close()
