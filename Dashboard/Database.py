import sqlite3
from datetime import datetime

DB_PATH = "sorting_dashboard.db"

# ══════════════════════════════════════════
#  INITIALIZATION
# ══════════════════════════════════════════

def init_db():
    """Create tables if they don't exist yet."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Current conveyor state
    c.execute("""
        CREATE TABLE IF NOT EXISTS conveyors (
            id      INTEGER PRIMARY KEY,
            running INTEGER NOT NULL DEFAULT 1,
            speed   REAL    NOT NULL DEFAULT 1.2
        )
    """)

    # Current servo state
    c.execute("""
        CREATE TABLE IF NOT EXISTS servos (
            type   TEXT PRIMARY KEY,
            active INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Object counters
    c.execute("""
        CREATE TABLE IF NOT EXISTS counts (
            type  TEXT PRIMARY KEY,
            value INTEGER NOT NULL DEFAULT 0
        )
    """)

    # General stats (unrecognized count, session start)
    c.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # Full event history
    c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp  TEXT    NOT NULL,
            category   TEXT    NOT NULL,
            action     TEXT    NOT NULL,
            details    TEXT
        )
    """)

    # Default data if tables are empty
    c.execute("INSERT OR IGNORE INTO conveyors (id, running, speed) VALUES (1, 1, 1.4)")
    c.execute("INSERT OR IGNORE INTO conveyors (id, running, speed) VALUES (2, 1, 1.2)")

    for t in ["applicator", "ihmulator", "sharps", "hazardous"]:
        c.execute("INSERT OR IGNORE INTO servos (type, active) VALUES (?, 0)", (t,))
        c.execute("INSERT OR IGNORE INTO counts (type, value) VALUES (?, 0)", (t,))

    c.execute("INSERT OR IGNORE INTO stats (key, value) VALUES ('unrecognized', '0')")
    c.execute("INSERT OR IGNORE INTO stats (key, value) VALUES ('session_start', ?)",
              (datetime.now().isoformat(),))

    conn.commit()
    conn.close()


# ══════════════════════════════════════════
#  CONVEYORS
# ══════════════════════════════════════════

def get_conveyors():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id, running, speed FROM conveyors ORDER BY id").fetchall()
    conn.close()
    return {r[0]: {"id": r[0], "running": bool(r[1]), "speed": r[2]} for r in rows}

def save_conveyor(conv_id, running, speed):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE conveyors SET running=?, speed=? WHERE id=?",
                 (1 if running else 0, speed, conv_id))
    conn.commit()
    conn.close()
    log_event("conveyor", f"Conveyor {conv_id} {'started' if running else 'stopped'}",
              f"speed={speed} m/s")


# ══════════════════════════════════════════
#  SERVOS
# ══════════════════════════════════════════

def get_servos():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT type, active FROM servos").fetchall()
    conn.close()
    return {r[0]: {"type": r[0], "active": bool(r[1])} for r in rows}

def save_servo(servo_type, active):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE servos SET active=? WHERE type=?",
                 (1 if active else 0, servo_type))
    conn.commit()
    conn.close()
    log_event("servo", f"Servo {servo_type} {'activated' if active else 'deactivated'}")


# ══════════════════════════════════════════
#  COUNTERS
# ══════════════════════════════════════════

def get_counts():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT type, value FROM counts").fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def increment_count(obj_type):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE counts SET value = value + 1 WHERE type=?", (obj_type,))
    conn.commit()
    conn.close()

def get_unrecognized():
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT value FROM stats WHERE key='unrecognized'").fetchone()
    conn.close()
    return int(row[0]) if row else 0

def increment_unrecognized():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE stats SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key='unrecognized'")
    conn.commit()
    conn.close()
    val = get_unrecognized()
    log_event("detection", "Unrecognized object", f"total={val}")
    return val

def get_session_start():
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT value FROM stats WHERE key='session_start'").fetchone()
    conn.close()
    return row[0] if row else datetime.now().isoformat()


# ══════════════════════════════════════════
#  EVENT HISTORY
# ══════════════════════════════════════════

def log_event(category, action, details=None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO events (timestamp, category, action, details) VALUES (?, ?, ?, ?)",
                 (datetime.now().isoformat(timespec='seconds'), category, action, details))
    conn.commit()
    conn.close()

def get_recent_events(limit=50):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT timestamp, category, action, details FROM events ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [{"timestamp": r[0], "category": r[1], "action": r[2], "details": r[3]} for r in rows]