#media_server.py
"""
Real HTTP control of local Plex / Jellyfin media servers.
Server URL + API token/key are read from config/api_keys.json:
  plex_url, plex_token
  jellyfin_url, jellyfin_api_key
"""
import sys
import json
from pathlib import Path

import requests

_REQUEST_TIMEOUT = 10


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _load_config() -> dict:
    try:
        path = _base_dir() / "config" / "api_keys.json"
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── Plex ──────────────────────────────────────────────────────────────────

def _plex_conf() -> tuple[str, str]:
    cfg = _load_config()
    return cfg.get("plex_url", "http://localhost:32400").rstrip("/"), cfg.get("plex_token", "")


def plex_search(query: str) -> str:
    if not query:
        return "No search query provided."
    url, token = _plex_conf()
    if not token:
        return "Plex token not configured (set 'plex_token' in config/api_keys.json)."

    try:
        r = requests.get(
            f"{url}/search",
            params={"query": query, "X-Plex-Token": token},
            headers={"Accept": "application/json"},
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        items = r.json().get("MediaContainer", {}).get("Metadata", [])
        if not items:
            return f"No Plex results for '{query}'."
        lines = [f"Plex results for '{query}':"]
        for m in items[:10]:
            title = m.get("title", "?")
            kind  = m.get("type", "?")
            year  = m.get("year", "")
            lines.append(f"  - {title} ({year}) [{kind}]")
        return "\n".join(lines)
    except requests.exceptions.ConnectionError:
        return f"Could not reach Plex at {url} — is the server running?"
    except requests.exceptions.Timeout:
        return "Plex did not respond in time."
    except Exception as e:
        return f"Plex error: {e}"


def plex_sessions() -> str:
    url, token = _plex_conf()
    if not token:
        return "Plex token not configured (set 'plex_token' in config/api_keys.json)."
    try:
        r = requests.get(
            f"{url}/status/sessions",
            params={"X-Plex-Token": token},
            headers={"Accept": "application/json"},
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        sessions = r.json().get("MediaContainer", {}).get("Metadata", [])
        if not sessions:
            return "Nothing is currently playing on Plex."
        lines = ["Now playing on Plex:"]
        for s in sessions:
            user = s.get("User", {}).get("title", "?")
            title = s.get("title", "?")
            lines.append(f"  - {title} (user: {user})")
        return "\n".join(lines)
    except requests.exceptions.ConnectionError:
        return f"Could not reach Plex at {url} — is the server running?"
    except Exception as e:
        return f"Plex error: {e}"


def plex_library_refresh() -> str:
    url, token = _plex_conf()
    if not token:
        return "Plex token not configured (set 'plex_token' in config/api_keys.json)."
    try:
        r = requests.get(
            f"{url}/library/sections/all/refresh",
            params={"X-Plex-Token": token},
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return "Plex library refresh triggered."
    except requests.exceptions.ConnectionError:
        return f"Could not reach Plex at {url} — is the server running?"
    except Exception as e:
        return f"Plex error: {e}"


# ── Jellyfin ──────────────────────────────────────────────────────────────

def _jellyfin_conf() -> tuple[str, str]:
    cfg = _load_config()
    return (
        cfg.get("jellyfin_url", "http://localhost:8096").rstrip("/"),
        cfg.get("jellyfin_api_key", ""),
    )


def jellyfin_search(query: str) -> str:
    if not query:
        return "No search query provided."
    url, api_key = _jellyfin_conf()
    if not api_key:
        return "Jellyfin API key not configured (set 'jellyfin_api_key' in config/api_keys.json)."

    try:
        r = requests.get(
            f"{url}/Items",
            params={"searchTerm": query, "Recursive": "true", "Limit": 10},
            headers={"X-Emby-Token": api_key},
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        items = r.json().get("Items", [])
        if not items:
            return f"No Jellyfin results for '{query}'."
        lines = [f"Jellyfin results for '{query}':"]
        for it in items:
            lines.append(f"  - {it.get('Name', '?')} [{it.get('Type', '?')}]")
        return "\n".join(lines)
    except requests.exceptions.ConnectionError:
        return f"Could not reach Jellyfin at {url} — is the server running?"
    except requests.exceptions.Timeout:
        return "Jellyfin did not respond in time."
    except Exception as e:
        return f"Jellyfin error: {e}"


def jellyfin_sessions() -> str:
    url, api_key = _jellyfin_conf()
    if not api_key:
        return "Jellyfin API key not configured (set 'jellyfin_api_key' in config/api_keys.json)."
    try:
        r = requests.get(
            f"{url}/Sessions",
            headers={"X-Emby-Token": api_key},
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        sessions = [s for s in r.json() if s.get("NowPlayingItem")]
        if not sessions:
            return "Nothing is currently playing on Jellyfin."
        lines = ["Now playing on Jellyfin:"]
        for s in sessions:
            user  = s.get("UserName", "?")
            title = s.get("NowPlayingItem", {}).get("Name", "?")
            lines.append(f"  - {title} (user: {user})")
        return "\n".join(lines)
    except requests.exceptions.ConnectionError:
        return f"Could not reach Jellyfin at {url} — is the server running?"
    except Exception as e:
        return f"Jellyfin error: {e}"


def control_media_server(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    parameters:
        server : plex | jellyfin (required)
        action : search | sessions | refresh_library (required)
        query  : search term (for 'search')
    """
    params  = parameters or {}
    server  = params.get("server", "").lower().strip()
    action  = params.get("action", "").lower().strip()
    query   = params.get("query", "")

    if player:
        player.write_log(f"[MediaServer] {server}:{action}")

    try:
        if server == "plex":
            if action == "search":
                return plex_search(query)
            if action == "sessions":
                return plex_sessions()
            if action == "refresh_library":
                return plex_library_refresh()
            return f"Unknown Plex action: '{action}'"

        if server == "jellyfin":
            if action == "search":
                return jellyfin_search(query)
            if action == "sessions":
                return jellyfin_sessions()
            return f"Unknown Jellyfin action: '{action}'"

        return "Please specify server='plex' or server='jellyfin'."

    except Exception as e:
        return f"control_media_server failed: {e}"
