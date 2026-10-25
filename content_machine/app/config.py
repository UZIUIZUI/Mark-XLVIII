import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UPLOADS = DATA / "uploads"
VIDEOS = DATA / "videos"
for _d in (UPLOADS, VIDEOS):
    _d.mkdir(parents=True, exist_ok=True)


def _load_env():
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()


def env(key, default=""):
    return os.environ.get(key, default).strip()


GEMINI_API_KEY = env("GEMINI_API_KEY")
TEXT_MODEL = env("TEXT_MODEL", "gemini-2.5-flash")
VIDEO_MODEL = env("VIDEO_MODEL", "veo-3.1-generate-preview")
VIDEO_RESOLUTION = env("VIDEO_RESOLUTION", "4k").lower()
IG_USER_ID = env("IG_USER_ID")
IG_ACCESS_TOKEN = env("IG_ACCESS_TOKEN")
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL").rstrip("/")
TIKTOK_ACCESS_TOKEN = env("TIKTOK_ACCESS_TOKEN")
TIKTOK_PRIVACY = env("TIKTOK_PRIVACY", "SELF_ONLY")

_tok = DATA / "token.txt"
APP_TOKEN = env("APP_TOKEN")
if not APP_TOKEN:
    if not _tok.exists():
        _tok.write_text(secrets.token_urlsafe(12))
    APP_TOKEN = _tok.read_text().strip()

MOCK = not GEMINI_API_KEY


def platform_status():
    return {
        "instagram": bool(IG_USER_ID and IG_ACCESS_TOKEN and PUBLIC_BASE_URL),
        "tiktok": bool(TIKTOK_ACCESS_TOKEN),
        "ai": not MOCK,
    }
