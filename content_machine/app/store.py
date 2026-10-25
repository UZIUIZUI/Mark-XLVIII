"""Winziger SQLite-Store fuer Posts, Analysen und Einstellungen."""
import json
import sqlite3
import threading
import time
import uuid

from .config import DATA

_lock = threading.RLock()
_db = sqlite3.connect(DATA / "machine.db", check_same_thread=False)
_db.row_factory = sqlite3.Row
JSON_COLS = {"hashtags", "platforms", "results", "files", "result"}

_db.executescript("""
CREATE TABLE IF NOT EXISTS posts(
  id TEXT PRIMARY KEY, created REAL, status TEXT, source TEXT, topic TEXT, hook TEXT,
  video_prompt TEXT, caption TEXT, hashtags TEXT, platforms TEXT, video_path TEXT,
  upload_path TEXT, secret TEXT, error TEXT, results TEXT);
CREATE TABLE IF NOT EXISTS analyses(
  id TEXT PRIMARY KEY, created REAL, status TEXT, files TEXT, note TEXT, result TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
""")

DEFAULT_SETTINGS = {
    "niche": "",
    "autopilot": False,
    "interval_hours": 12,
    "videos_per_run": 1,
    "platforms": ["instagram", "tiktok"],
    "auto_publish": False,  # False = erst in der Warteschlange freigeben
    "last_run": 0,
}


def _enc(k, v):
    return json.dumps(v, ensure_ascii=False) if k in JSON_COLS else v


def _dec(row):
    if row is None:
        return None
    d = dict(row)
    for k in JSON_COLS & d.keys():
        if d[k] is not None:
            d[k] = json.loads(d[k])
    return d


def insert(table, **kw):
    kw.setdefault("id", uuid.uuid4().hex[:10])
    kw.setdefault("created", time.time())
    with _lock:
        cols = ",".join(kw)
        _db.execute(f"INSERT INTO {table}({cols}) VALUES({','.join('?' * len(kw))})",
                    [_enc(k, v) for k, v in kw.items()])
        _db.commit()
    return kw["id"]


def update(table, id, **kw):
    with _lock:
        sets = ",".join(f"{k}=?" for k in kw)
        _db.execute(f"UPDATE {table} SET {sets} WHERE id=?", [*[_enc(k, v) for k, v in kw.items()], id])
        _db.commit()


def get(table, id):
    with _lock:
        return _dec(_db.execute(f"SELECT * FROM {table} WHERE id=?", (id,)).fetchone())


def listing(table, limit=50):
    with _lock:
        rows = _db.execute(f"SELECT * FROM {table} ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
    return [_dec(r) for r in rows]


def delete(table, id):
    with _lock:
        _db.execute(f"DELETE FROM {table} WHERE id=?", (id,))
        _db.commit()


def get_settings():
    with _lock:
        rows = _db.execute("SELECT k,v FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["k"]: json.loads(r["v"]) for r in rows})
    return s


def set_settings(**kw):
    with _lock:
        for k, v in kw.items():
            if k in DEFAULT_SETTINGS:
                _db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, json.dumps(v)))
        _db.commit()
