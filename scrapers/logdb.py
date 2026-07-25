import sqlite3
import threading
from pathlib import Path
from typing import List

DB_FILE = Path(__file__).parent.parent / "results" / "logs.db"

_connection: sqlite3.Connection = None
_db_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        DB_FILE.parent.mkdir(exist_ok=True)
        _connection = sqlite3.connect(DB_FILE, check_same_thread=False)
        _connection.execute(
            "CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, line TEXT NOT NULL)"
        )
        _connection.commit()
    return _connection


def append(formatted_line: str) -> None:
    with _db_lock:
        conn = _connect()
        conn.execute("INSERT INTO logs (line) VALUES (?)", (formatted_line,))
        conn.commit()


def load_recent(limit: int) -> List[str]:
    with _db_lock:
        conn = _connect()
        rows = conn.execute("SELECT line FROM logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [row[0] for row in reversed(rows)]
