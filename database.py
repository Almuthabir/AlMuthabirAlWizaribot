
import sqlite3
from datetime import date, timedelta
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DB_PATH = "wizari.db"

def get_conn():
    """Establishes and returns a database connection."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logging.error(f"Database connection error: {e}")
        return None

def init_db():
    """Initializes the database schema if tables do not exist."""
    conn = get_conn()
    if conn is None: return
    try:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS users (
                user_id        INTEGER PRIMARY KEY,
                name           TEXT,
                xp             INTEGER DEFAULT 0,
                streak         INTEGER DEFAULT 0,
                last_date      TEXT,
                total_games    INTEGER DEFAULT 0,
                reminders_on   INTEGER DEFAULT 0,
                reminder_time  TEXT DEFAULT '20:00',
                active_title   TEXT DEFAULT NULL,
                title_announce INTEGER DEFAULT 1
            )""")
        c.execute("""CREATE TABLE IF NOT EXISTS subject_stats (
                user_id  INTEGER, subject  TEXT,
                games    INTEGER DEFAULT 0, correct  INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, subject))""")
        c.execute("""CREATE TABLE IF NOT EXISTS challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenger INTEGER, opponent INTEGER, subject TEXT,
                status TEXT DEFAULT 'pending',
                challenger_score INTEGER DEFAULT -1, opponent_score INTEGER DEFAULT -1,
                created_at TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS weekly_stats (
                user_id INTEGER, week TEXT,
                games INTEGER DEFAULT 0, correct INTEGER DEFAULT 0, xp INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, week))""")
        c.execute("""CREATE TABLE IF NOT EXISTS group_sessions (
                session_id TEXT PRIMARY KEY, owner_id INTEGER, owner_name TEXT,
                subject TEXT, status TEXT DEFAULT 'waiting',
                chat_id INTEGER, msg_id INTEGER, created_at TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS session_players (
                session_id TEXT, user_id INTEGER, user_name TEXT,
                score INTEGER DEFAULT 0, finished INTEGER DEFAULT 0,
                PRIMARY KEY (session_id, user_id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS user_titles (
                user_id INTEGER, title_key TEXT, earned_at TEXT,
                PRIMARY KEY (user_id, title_key))""")
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Database initialization error: {e}")
    finally:
        if conn: conn.close()

def register_user(user_id, name):
    """Registers a new user or updates an existing user's name."""
    conn = get_conn()
    if conn is None: return
    try:
        conn.execute("INSERT OR IGNORE INTO users (user_id, name) VALUES (?, ?)", (user_id, name))
        conn.execute("UPDATE users SET name=? WHERE user_id=?", (name, user_id))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error registering user {user_id}: {e}")
    finally:
        if conn: conn.close()

def get_user_stats(user_id):
    """Retrieves a user's statistics."""
    conn = get_conn()
    if conn is None: return {}
    row = None
    try:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    except sqlite3.Error as e:
        logging.error(f"Error getting stats for user {user_id}: {e}")
    finally:
        if conn: conn.close()
    if not row:
        return {"xp":0,"streak":0,"total_games":0,"reminders_on":0,
                "reminder_time":"20:00","active_title":None,"title_announce":1}
    return dict(row)

def update_stats(user_id, earned_xp, correct, total, subject):
    """Updates user statistics after a game, including XP, streak, and subject stats."""
    conn = get_conn()
    if conn is None: return 0
    row = None
    try:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row: conn.close(); return 0
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        streak = row["streak"]; bonus_xp = 0
        if row["last_date"] == today: pass
        elif row["last_date"] == yesterday:
            streak += 1
            if streak % 7 == 0: bonus_xp = 50
        else: streak = 1
        total_xp = earned_xp + bonus_xp
        conn.execute("UPDATE users SET xp=xp+?, streak=?, last_date=?, total_games=total_games+1 WHERE user_id=?",
            (total_xp, streak, today, user_id))
        conn.execute("INSERT OR IGNORE INTO subject_stats (user_id, subject) VALUES (?, ?)", (user_id, subject))
        conn.execute("UPDATE subject_stats SET games=games+1, correct=correct+? WHERE user_id=? AND subject=?",
            (correct, user_id, subject))
        week = date.today().strftime("%Y-W%W")
        conn.execute("INSERT OR IGNORE INTO weekly_stats (user_id, week) VALUES (?, ?)", (user_id, week))
        conn.execute("UPDATE weekly_stats SET games=games+1, correct=correct+?, xp=xp+? WHERE user_id=? AND week=?",
            (correct, total_xp, user_id, week))
        conn.commit()
        return bonus_xp
    except sqlite3.Error as e:
        logging.error(f"Error updating stats for user {user_id}: {e}")
        return 0
    finally:
        if conn: conn.close()

def add_daily_login_xp(user_id):
    """Adds daily login XP to a user if they haven't logged in today."""
    conn = get_conn()
    if conn is None: return False
    row = None
    try:
        row = conn.execute("SELECT last_date FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row: conn.close(); return False
        today = date.today().isoformat()
        if row["last_date"] == today: conn.close(); return False
        conn.execute("UPDATE users SET xp=xp+20 WHERE user_id=?", (user_id,))
        conn.commit()
        return True
    except sqlite3.Error as e:
        logging.error(f"Error adding daily login XP for user {user_id}: {e}")
        return False
    finally:
        if conn: conn.close()

def get_leaderboard(limit=10):
    """Retrieves the top users for the leaderboard."""
    conn = get_conn()
    if conn is None: return []
    rows = []
    try:
        rows = conn.execute("SELECT name, xp, streak, active_title FROM users ORDER BY xp DESC LIMIT ?", (limit,)).fetchall()
    except sqlite3.Error as e:
        logging.error(f"Error getting leaderboard: {e}")
    finally:
        if conn: conn.close()
    return [dict(r) for r in rows]

def get_subject_stats(user_id):
    """Retrieves a user's statistics for each subject."""
    conn = get_conn()
    if conn is None: return {}
    rows = []
    try:
        rows = conn.execute("SELECT subject, games, correct FROM subject_stats WHERE user_id=?", (user_id,)).fetchall()
    except sqlite3.Error as e:
        logging.error(f"Error getting subject stats for user {user_id}: {e}")
    finally:
        if conn: conn.close()
    return {r["subject"]: dict(r) for r in rows}

def get_weekly_report(user_id):
    """Retrieves a user's weekly report."""
    conn = get_conn()
    if conn is None: return {"games":0,"correct":0,"xp":0}
    row = None
    try:
        week = date.today().strftime("%Y-W%W")
        row = conn.execute("SELECT * FROM weekly_stats WHERE user_id=? AND week=?", (user_id, week)).fetchone()
    except sqlite3.Error as e:
        logging.error(f"Error getting weekly report for user {user_id}: {e}")
    finally:
        if conn: conn.close()
    return dict(row) if row else {"games":0,"correct":0,"xp":0}

def set_reminder(user_id, on, time_str="20:00"):
    """Sets or updates a user's daily reminder preference and time."""
    conn = get_conn()
    if conn is None: return
    try:
        conn.execute("UPDATE users SET reminders_on=?, reminder_time=? WHERE user_id=?", (1 if on else 0, time_str, user_id))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error setting reminder for user {user_id}: {e}")
    finally:
        if conn: conn.close()

def get_reminder_users():
    """Retrieves a list of users who have reminders enabled."""
    conn = get_conn()
    if conn is None: return []
    rows = []
    try:
        rows = conn.execute("SELECT user_id, name, reminder_time, active_title, title_announce FROM users WHERE reminders_on=1").fetchall()
    except sqlite3.Error as e:
        logging.error(f"Error getting reminder users: {e}")
    finally:
        if conn: conn.close()
    return [dict(r) for r in rows]

def get_user_by_username_search(name):
    """Searches for users by a partial username match."""
    conn = get_conn()
    if conn is None: return []
    rows = []
    try:
        rows = conn.execute("SELECT user_id, name FROM users WHERE name LIKE ? LIMIT 5", (f"%{name}%",)).fetchall()
    except sqlite3.Error as e:
        logging.error(f"Error searching for user by name '{name}': {e}")
    finally:
        if conn: conn.close()
    return [dict(r) for r in rows]

# ── Title functions ──
def get_user_earned_titles(user_id):
    """Retrieves a list of titles earned by a user."""
    conn = get_conn()
    if conn is None: return []
    rows = []
    try:
        rows = conn.execute("SELECT title_key FROM user_titles WHERE user_id=?", (user_id,)).fetchall()
    except sqlite3.Error as e:
        logging.error(f"Error getting earned titles for user {user_id}: {e}")
    finally:
        if conn: conn.close()
    return [r["title_key"] for r in rows]

def earn_title(user_id, title_key):
    """Records that a user has earned a new title."""
    conn = get_conn()
    if conn is None: return
    try:
        today = date.today().isoformat()
        conn.execute("INSERT OR IGNORE INTO user_titles (user_id, title_key, earned_at) VALUES (?, ?, ?)", (user_id, title_key, today))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error earning title '{title_key}' for user {user_id}: {e}")
    finally:
        if conn: conn.close()

def set_active_title(user_id, title_key):
    """Sets a user's active title."""
    conn = get_conn()
    if conn is None: return
    try:
        conn.execute("UPDATE users SET active_title=? WHERE user_id=?", (title_key, user_id))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error setting active title '{title_key}' for user {user_id}: {e}")
    finally:
        if conn: conn.close()

def set_title_announce(user_id, on):
    """Sets whether a user's active title should be announced."""
    conn = get_conn()
    if conn is None: return
    try:
        conn.execute("UPDATE users SET title_announce=? WHERE user_id=?", (1 if on else 0, user_id))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error setting title announce for user {user_id}: {e}")
    finally:
        if conn: conn.close()

# ── Challenge functions ──
def create_challenge(challenger, opponent, subject):
    """Creates a new challenge entry in the database."""
    conn = get_conn()
    if conn is None: return None
    cid = None
    try:
        cur = conn.execute("INSERT INTO challenges (challenger, opponent, subject, created_at) VALUES (?, ?, ?, ?)",
            (challenger, opponent, subject, date.today().isoformat()))
        cid = cur.lastrowid
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error creating challenge between {challenger} and {opponent}: {e}")
    finally:
        if conn: conn.close()
    return cid

def get_challenge(challenge_id):
    """Retrieves details of a specific challenge."""
    conn = get_conn()
    if conn is None: return None
    row = None
    try:
        row = conn.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
    except sqlite3.Error as e:
        logging.error(f"Error getting challenge {challenge_id}: {e}")
    finally:
        if conn: conn.close()
    return dict(row) if row else None

def update_challenge_score(challenge_id, is_challenger, score):
    """Updates the score for a player in a challenge and potentially finishes the challenge."""
    conn = get_conn()
    if conn is None: return
    try:
        field = "challenger_score" if is_challenger else "opponent_score"
        conn.execute(f"UPDATE challenges SET {field}=? WHERE id=?", (score, challenge_id))
        row = conn.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
        if row and row["challenger_score"] >= 0 and row["opponent_score"] >= 0:
            conn.execute("UPDATE challenges SET status='finished' WHERE id=?", (challenge_id,))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error updating challenge {challenge_id} score: {e}")
    finally:
        if conn: conn.close()

def get_pending_challenge(user_id):
    """Retrieves any pending challenge for a given user."""
    conn = get_conn()
    if conn is None: return None
    row = None
    try:
        row = conn.execute("SELECT * FROM challenges WHERE opponent=? AND status='pending'", (user_id,)).fetchone()
    except sqlite3.Error as e:
        logging.error(f"Error getting pending challenge for user {user_id}: {e}")
    finally:
        if conn: conn.close()
    return dict(row) if row else None

def cleanup_old_challenges():
    """Cleans up old, expired challenges."""
    conn = get_conn()
    if conn is None: return
    try:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        conn.execute("UPDATE challenges SET status='expired' WHERE status='pending' AND created_at < ?", (yesterday,))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error cleaning up old challenges: {e}")
    finally:
        if conn: conn.close()

# ── Group Session functions ──
def create_session(session_id, owner_id, owner_name, subject, chat_id):
    """Creates a new group session."""
    conn = get_conn()
    if conn is None: return
    try:
        conn.execute("INSERT OR REPLACE INTO group_sessions (session_id, owner_id, owner_name, subject, chat_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, owner_id, owner_name, subject, chat_id, date.today().isoformat()))
        conn.execute("INSERT OR IGNORE INTO session_players (session_id, user_id, user_name) VALUES (?, ?, ?)",
            (session_id, owner_id, owner_name))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error creating session {session_id}: {e}")
    finally:
        if conn: conn.close()

def get_session(session_id):
    """Retrieves details of a group session."""
    conn = get_conn()
    if conn is None: return None
    row = None
    try:
        row = conn.execute("SELECT * FROM group_sessions WHERE session_id=?", (session_id,)).fetchone()
    except sqlite3.Error as e:
        logging.error(f"Error getting session {session_id}: {e}")
    finally:
        if conn: conn.close()
    return dict(row) if row else None

def join_session(session_id, user_id, user_name):
    """Adds a user to an existing group session."""
    conn = get_conn()
    if conn is None: return False
    try:
        count = conn.execute("SELECT COUNT(*) as c FROM session_players WHERE session_id=?", (session_id,)).fetchone()["c"]
        session = conn.execute("SELECT status FROM group_sessions WHERE session_id=?", (session_id,)).fetchone()
        if not session or session["status"] != "waiting" or count >= 25:
            conn.close(); return False
        conn.execute("INSERT OR IGNORE INTO session_players (session_id, user_id, user_name) VALUES (?, ?, ?)",
            (session_id, user_id, user_name))
        conn.commit()
        return True
    except sqlite3.Error as e:
        logging.error(f"Error joining session {session_id} for user {user_id}: {e}")
        return False
    finally:
        if conn: conn.close()

def get_session_players(session_id):
    """Retrieves all players in a group session."""
    conn = get_conn()
    if conn is None: return []
    rows = []
    try:
        rows = conn.execute("SELECT * FROM session_players WHERE session_id=? ORDER BY score DESC", (session_id,)).fetchall()
    except sqlite3.Error as e:
        logging.error(f"Error getting session players for session {session_id}: {e}")
    finally:
        if conn: conn.close()
    return [dict(r) for r in rows]

def start_session(session_id):
    """Sets the status of a group session to active."""
    conn = get_conn()
    if conn is None: return
    try:
        conn.execute("UPDATE group_sessions SET status='active' WHERE session_id=?", (session_id,))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error starting session {session_id}: {e}")
    finally:
        if conn: conn.close()

def update_session_score(session_id, user_id, score):
    """Updates a player's score in a group session."""
    conn = get_conn()
    if conn is None: return
    try:
        conn.execute("UPDATE session_players SET score=?, finished=1 WHERE session_id=? AND user_id=?",
            (score, session_id, user_id))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error updating session {session_id} score for user {user_id}: {e}")
    finally:
        if conn: conn.close()

def finish_session(session_id):
    """Sets the status of a group session to finished."""
    conn = get_conn()
    if conn is None: return
    try:
        conn.execute("UPDATE group_sessions SET status='finished' WHERE session_id=?", (session_id,))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error finishing session {session_id}: {e}")
    finally:
        if conn: conn.close()

def set_session_msg(session_id, msg_id):
    """Sets the message ID associated with a group session."""
    conn = get_conn()
    if conn is None: return
    try:
        conn.execute("UPDATE group_sessions SET msg_id=? WHERE session_id=?", (msg_id, session_id))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error setting session {session_id} message ID: {e}")
    finally:
        if conn: conn.close()

def get_finished_count(session_id):
    """Returns the count of finished players and total players in a session."""
    conn = get_conn()
    if conn is None: return 0, 0
    total, finished = 0, 0
    try:
        total = conn.execute("SELECT COUNT(*) as c FROM session_players WHERE session_id=?", (session_id,)).fetchone()["c"]
        finished = conn.execute("SELECT COUNT(*) as c FROM session_players WHERE session_id=? AND finished=1", (session_id,)).fetchone()["c"]
    except sqlite3.Error as e:
        logging.error(f"Error getting finished count for session {session_id}: {e}")
    finally:
        if conn: conn.close()
    return finished, total

def cleanup_old_sessions():
    """Cleans up old, waiting group sessions."""
    conn = get_conn()
    if conn is None: return
    try:
        conn.execute("DELETE FROM group_sessions WHERE status='waiting' AND created_at < date('now', '-1 day')")
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error cleaning up old sessions: {e}")
    finally:
        if conn: conn.close()

