"""
Screen memory for MARK XL.

Pipeline:
    [Screenshot im RAM] -> [KI liest das Bild] -> [Speichert nur Text in der Datenbank]

The screenshot/camera frame itself is never persisted — only the AI's text
summary of what it saw. Stored in SQLite, split into:
    - Kurzzeitgedaechtnis : everything from the last N minutes (get_short_term_memory)
    - Langzeitgedaechtnis : entries flagged is_important=True, kept past cleanup
"""
import sys
from datetime import datetime
from pathlib import Path
from sqlite3 import connect
from threading import Lock


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_DB_PATH = _base_dir() / "memory" / "screen_memory.db"


class ScreenMemory:
    def __init__(self, db_path: Path | str = _DB_PATH):
        self._lock = Lock()
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = connect(db_path, check_same_thread=False)
        self._create_tables()

    def _create_tables(self) -> None:
        with self._lock:
            self._conn.execute('''
                CREATE TABLE IF NOT EXISTS screen_history (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       DATETIME,
                    app_or_website  TEXT,
                    summary         TEXT,
                    tags            TEXT,
                    is_important    INTEGER DEFAULT 0
                )
            ''')
            self._conn.commit()

    def add_memory(
        self,
        app_or_website: str,
        summary:        str,
        tags:           str  = "",
        is_important:   bool = False,
    ) -> None:
        """Speichert eine neue Beobachtung als Text (kein Bild)."""
        with self._lock:
            self._conn.execute('''
                INSERT INTO screen_history (timestamp, app_or_website, summary, tags, is_important)
                VALUES (?, ?, ?, ?, ?)
            ''', (datetime.now(), app_or_website, summary, tags, 1 if is_important else 0))
            self._conn.commit()
        print(f"[ScreenMemory] Gemerkt: {app_or_website} -> {summary[:50]}...")

    def get_short_term_memory(self, minutes: int = 30) -> list[tuple]:
        """Holt die Erinnerungen der letzten X Minuten."""
        with self._lock:
            cursor = self._conn.execute('''
                SELECT timestamp, app_or_website, summary
                FROM screen_history
                WHERE timestamp >= datetime('now', ?)
                ORDER BY timestamp DESC
            ''', (f'-{minutes} minutes',))
            return cursor.fetchall()

    def search_long_term_memory(self, keyword: str) -> list[tuple]:
        """Sucht im gesamten Gedaechtnis nach Stichworten, App/Website oder Tags."""
        with self._lock:
            cursor = self._conn.execute('''
                SELECT timestamp, app_or_website, summary
                FROM screen_history
                WHERE app_or_website LIKE ? OR summary LIKE ? OR tags LIKE ?
                ORDER BY timestamp DESC
            ''', (f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'))
            return cursor.fetchall()

    def cleanup_old_short_term(self, days_to_keep: int = 7) -> None:
        """Loescht unwichtige Kurzzeit-Erinnerungen nach ein paar Tagen, behaelt Wichtiges."""
        with self._lock:
            self._conn.execute('''
                DELETE FROM screen_history
                WHERE is_important = 0 AND timestamp < datetime('now', ?)
            ''', (f'-{days_to_keep} days',))
            self._conn.commit()
        print("[ScreenMemory] Alte unbedeutende Kurzzeit-Erinnerungen aufgeraeumt.")


_memory: ScreenMemory | None = None


def get_screen_memory() -> ScreenMemory:
    """Lazily created, process-wide singleton."""
    global _memory
    if _memory is None:
        _memory = ScreenMemory()
    return _memory
