import json
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sorting_dashboard.db")


def _connect() -> sqlite3.Connection:
    """Open the local SQLite file (no network required)."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    return sqlite3.connect(DB_PATH, timeout=30.0)

# ══════════════════════════════════════════
#  CATEGORIES
# ══════════════════════════════════════════
# applicator  – Servo 3
# inhaler     – Servo 4
# chemical    – Servo 2
# canister    – Servo 1
CATEGORIES = ["applicator", "inhaler", "chemical", "canister"]

LAMP_KEYS = ("red", "orange", "green", "blue")
_DEFAULT_LAMPS = {k: False for k in LAMP_KEYS}

# ══════════════════════════════════════════
#  INITIALIZATION
# ══════════════════════════════════════════

def init_db():
    """Create tables if they don't exist yet (safe to run on existing DB)."""
    conn = _connect()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS conveyors (
            id      INTEGER PRIMARY KEY,
            running INTEGER NOT NULL DEFAULT 1,
            speed   REAL    NOT NULL DEFAULT 1.2
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS servos (
            type   TEXT PRIMARY KEY,
            active INTEGER NOT NULL DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS counts (
            type  TEXT PRIMARY KEY,
            value INTEGER NOT NULL DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp  TEXT    NOT NULL,
            category   TEXT    NOT NULL,
            action     TEXT    NOT NULL,
            details    TEXT
        )
    """)

    # Single physical conveyor (dashboard mirrors state to rows 1 & 2 in the UI)
    c.execute("INSERT OR IGNORE INTO conveyors (id, running, speed) VALUES (1, 0, 1.4)")
    c.execute("DELETE FROM conveyors WHERE id != 1")

    # Seed all 4 categories and unsorted counter
    for t in CATEGORIES:
        c.execute("INSERT OR IGNORE INTO servos (type, active) VALUES (?, 0)", (t,))
        c.execute("INSERT OR IGNORE INTO counts (type, value) VALUES (?, 0)", (t,))
    c.execute("INSERT OR IGNORE INTO counts (type, value) VALUES ('unsorted', 0)")

    # Migrate legacy 'sharps' rows to the new 'chemical' category.
    c.execute("INSERT OR IGNORE INTO servos (type, active) SELECT 'chemical', active FROM servos WHERE type = 'sharps'")
    c.execute("UPDATE servos SET active = 1 WHERE type = 'chemical' AND EXISTS (SELECT 1 FROM servos WHERE type = 'sharps' AND active = 1)")
    c.execute("DELETE FROM servos WHERE type = 'sharps'")

    c.execute("INSERT OR IGNORE INTO counts (type, value) SELECT 'chemical', value FROM counts WHERE type = 'sharps'")
    c.execute("UPDATE counts SET value = value + (SELECT value FROM counts WHERE type = 'sharps') WHERE type = 'chemical' AND EXISTS (SELECT 1 FROM counts WHERE type = 'sharps')")
    c.execute("DELETE FROM counts WHERE type = 'sharps'")

    # Remove old 'hazardous' rows if they exist from a previous DB schema
    c.execute("DELETE FROM servos WHERE type = 'hazardous'")
    c.execute("DELETE FROM counts WHERE type = 'hazardous'")

    c.execute("INSERT OR IGNORE INTO stats (key, value) VALUES ('unrecognized', '0')")
    c.execute("INSERT OR IGNORE INTO stats (key, value) VALUES ('sensor1_triggers', '[]')")
    c.execute(
        "INSERT OR IGNORE INTO stats (key, value) VALUES ('lamps', ?)",
        (json.dumps(_DEFAULT_LAMPS),),
    )

    c.execute("INSERT OR IGNORE INTO stats (key, value) VALUES ('session_start', ?)",(datetime.now().isoformat(),))

    conn.commit()
    conn.close()


# ══════════════════════════════════════════
#  STATUS LAMPS (local SQLite — no network)
# ══════════════════════════════════════════

def get_lamps() -> dict:
    conn = _connect()
    row = conn.execute("SELECT value FROM stats WHERE key='lamps'").fetchone()
    conn.close()
    if not row:
        return dict(_DEFAULT_LAMPS)
    try:
        stored = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return dict(_DEFAULT_LAMPS)
    return {k: bool(stored.get(k, False)) for k in LAMP_KEYS}


def save_lamps(lamps: dict) -> dict:
    state = {k: bool(lamps.get(k, False)) for k in LAMP_KEYS}
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO stats (key, value) VALUES ('lamps', ?)",
        (json.dumps(state),),
    )
    conn.commit()
    conn.close()
    return state


# ══════════════════════════════════════════
#  CONVEYORS
# ══════════════════════════════════════════

def get_conveyors():
    conn = _connect()
    rows = conn.execute("SELECT id, running FROM conveyors ORDER BY id").fetchall()
    conn.close()
    return {
        r[0]: {
            "id": r[0],
            "running": bool(r[1])
        }
        for r in rows
    }

def save_conveyor(conv_id, running):
    conn = _connect()
    conn.execute("UPDATE conveyors SET running=? WHERE id=?",(1 if running else 0, conv_id))
    conn.commit()
    conn.close()

# ══════════════════════════════════════════
#  SERVOS
# ══════════════════════════════════════════

def get_servos():
    conn = _connect()
    rows = conn.execute("SELECT type, active FROM servos").fetchall()
    conn.close()
    return {r[0]: {"type": r[0], "active": bool(r[1])} for r in rows}

def save_servo(servo_type, active):
    conn = _connect()
    conn.execute("UPDATE servos SET active=? WHERE type=?",(1 if active else 0, servo_type))
    conn.commit()
    conn.close()


def reset_all_servos():
    """Mark every servo inactive (e.g. when Arduino disconnects)."""
    conn = _connect()
    conn.execute("UPDATE servos SET active=0")
    conn.commit()
    conn.close()


# ══════════════════════════════════════════
#  COUNTERS
# ══════════════════════════════════════════

def get_counts():
    conn = _connect()
    rows = conn.execute("SELECT type, value FROM counts").fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def increment_count(obj_type):
    conn = _connect()
    conn.execute("INSERT OR IGNORE INTO counts (type, value) VALUES (?, 0)", (obj_type,))
    conn.execute("UPDATE counts SET value = value + 1 WHERE type=?", (obj_type,))
    conn.commit()
    conn.close()

def increment_unsorted():
    conn = _connect()
    conn.execute("INSERT OR IGNORE INTO counts (type, value) VALUES ('unsorted', 0)")
    conn.execute("UPDATE counts SET value = value + 1 WHERE type='unsorted'")
    conn.commit()
    row = conn.execute("SELECT value FROM counts WHERE type='unsorted'").fetchone()
    conn.close()
    return int(row[0]) if row else 0

def get_unrecognized():
    conn = _connect()
    row = conn.execute("SELECT value FROM stats WHERE key='unrecognized'").fetchone()
    conn.close()
    return int(row[0]) if row else 0


def increment_unrecognized():
    conn = _connect()
    conn.execute(
        "UPDATE stats SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key='unrecognized'"
    )
    conn.commit()
    conn.close()
    return get_unrecognized()

def get_session_start():
    conn = _connect()
    row = conn.execute("SELECT value FROM stats WHERE key='session_start'").fetchone()
    conn.close()
    return row[0] if row else datetime.now().isoformat()


# ══════════════════════════════════════════
#  SENSOR 1 — sorting rate (objects / hour)
# ══════════════════════════════════════════

_SENSOR1_MAX = 200


def record_sensor1_trigger(ts=None):
    """Record a sensor-1 trigger timestamp (unix float, ISO stored in DB)."""
    if ts is None:
        ts = datetime.now().timestamp()
    conn = _connect()
    row = conn.execute("SELECT value FROM stats WHERE key='sensor1_triggers'").fetchone()
    triggers = json.loads(row[0]) if row else []
    triggers.append(float(ts))
    triggers = triggers[-_SENSOR1_MAX:]
    conn.execute(
        "INSERT OR REPLACE INTO stats (key, value) VALUES ('sensor1_triggers', ?)",
        (json.dumps(triggers),),
    )
    conn.commit()
    conn.close()
    return triggers


def get_sorted_device(limit=10):
    conn = _connect()

    rows = conn.execute("""
        SELECT timestamp
        FROM events
        WHERE category='detection'
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,)).fetchall()

    conn.close()

    return sorted(datetime.fromisoformat(r[0]).timestamp()for r in rows)

def compute_sorting_rate(limit=10):
    "Sorting rate (objects/hour) based on recent detection timestamps."
    triggers = get_sorted_device(limit)
    if len(triggers) < 2:
        return 0
    window = triggers[-1] - triggers[0]
    if window < 1.0:
        window = 1.0
    return round((len(triggers) / window) * 3600)

# ══════════════════════════════════════════
#  EVENT HISTORY
# ══════════════════════════════════════════

def log_event(category, action, details=None):

    conn = _connect()
    conn.execute("INSERT INTO events (timestamp, category, action, details) VALUES (?, ?, ?, ?)",
                (datetime.now().isoformat(timespec='seconds'), category, action, details))
    conn.commit()
    conn.close()

def get_recent_events(limit=50, categories=None):
    """
    Return recent events ordered newest-first.
    Pass categories=["detection","servo",...] to exclude noise like system connect/disconnect.
    """
    conn = _connect()
    if categories:
        placeholders = ",".join("?" * len(categories))
        rows = conn.execute(
            f"SELECT timestamp, category, action, details FROM events "
            f"WHERE category IN ({placeholders}) ORDER BY id DESC LIMIT ?",
            (*categories, limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT timestamp, category, action, details FROM events ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return [{"timestamp": r[0], "category": r[1], "action": r[2], "details": r[3]}
            for r in rows]