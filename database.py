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
            user_id     INTEGER PRIMARY KEY,
            name        TEXT,
            xp          INTEGER DEFAULT 0,
            streak      INTEGER DEFAULT 0,
            last_date   TEXT,
            total_games INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS subject_stats (
            user_id TEXT,
            subject TEXT,
            games   INTEGER DEFAULT 0,
            correct INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, subject)
        )
    """)

    conn.commit()
    conn.close()

def register_user(user_id: int, name: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, name) VALUES (?, ?)",
        (user_id, name)
    )
    conn.execute(
        "UPDATE users SET name=? WHERE user_id=?",
        (name, user_id)
    )
    conn.commit()
    conn.close()

def get_user_stats(user_id: int) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return {"xp": 0, "streak": 0, "total_games": 0}
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
        pass  # already played today, don't change streak
    elif last_date == yesterday:
        streak += 1
    else:
        streak = 1

    new_xp = row["xp"] + earned_xp
    new_games = row["total_games"] + 1

    conn.execute(
        "UPDATE users SET xp=?, streak=?, last_date=?, total_games=? WHERE user_id=?",
        (new_xp, streak, today, new_games, user_id)
    )

    # Update subject stats
    conn.execute(
        "INSERT OR IGNORE INTO subject_stats (user_id, subject) VALUES (?, ?)",
        (user_id, subject)
    )
    conn.execute(
        "UPDATE subject_stats SET games=games+1, correct=correct+? WHERE user_id=? AND subject=?",
        (correct, user_id, subject)
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
