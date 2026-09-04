#game_server.py
"""
Local dedicated game-server management (Minecraft, Valheim, etc.) plus a
generic Home Assistant REST bridge for smart-home actions.

Server profiles live in config/api_keys.json under "game_servers":
  {
    "game_servers": {
      "minecraft": {"path": "C:\\Servers\\mc\\run.bat", "cwd": "C:\\Servers\\mc"},
      "valheim":   {"path": "/opt/valheim/start_server.sh", "cwd": "/opt/valheim"}
    },
    "home_assistant_url": "http://homeassistant.local:8123",
    "home_assistant_token": "..."
  }
"""
import sys
import json
import time
from pathlib import Path

import requests

from actions.process_manager import start_process, stop_process, status_process

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


def _server_profile(server_name: str) -> dict | None:
    profiles = _load_config().get("game_servers", {})
    return profiles.get(server_name.lower())


# ── Local dedicated server lifecycle ────────────────────────────────────────

def start_game_server(server_name: str) -> str:
    profile = _server_profile(server_name)
    if not profile:
        return (
            f"No server profile named '{server_name}' in config. "
            f"Add it under 'game_servers' in config/api_keys.json."
        )
    exe = profile.get("path", "")
    if not exe or not Path(exe).exists():
        return f"Server executable/script not found: {exe}"

    return start_process(exe, args=profile.get("args", []), cwd=profile.get("cwd"))


def stop_game_server(server_name: str, confirm: bool = False) -> str:
    profile = _server_profile(server_name)
    process_name = (profile or {}).get("process_name") or Path(
        (profile or {}).get("path", server_name)
    ).name
    return stop_process(process_name, confirm=confirm)


def status_game_server(server_name: str) -> str:
    profile = _server_profile(server_name)
    process_name = (profile or {}).get("process_name") or Path(
        (profile or {}).get("path", server_name)
    ).name
    return status_process(process_name)


def list_game_servers() -> str:
    profiles = _load_config().get("game_servers", {})
    if not profiles:
        return "No game server profiles configured (see 'game_servers' in config/api_keys.json)."
    lines = ["Configured game servers:"]
    for name in profiles:
        lines.append(f"  - {name}: {status_game_server(name)}")
    return "\n".join(lines)


# ── Home Assistant bridge ───────────────────────────────────────────────────

def _ha_conf() -> tuple[str, str]:
    cfg = _load_config()
    return cfg.get("home_assistant_url", "").rstrip("/"), cfg.get("home_assistant_token", "")


def home_assistant_call(entity_id: str, service: str) -> str:
    """
    service examples: 'turn_on', 'turn_off', 'toggle' for a domain.entity_id
    e.g. entity_id='light.living_room', service='turn_on'
    """
    url, token = _ha_conf()
    if not url or not token:
        return "Home Assistant not configured (set 'home_assistant_url' and 'home_assistant_token')."
    if "." not in entity_id:
        return f"Invalid entity_id: '{entity_id}' (expected format domain.entity, e.g. light.living_room)."

    domain = entity_id.split(".", 1)[0]
    try:
        r = requests.post(
            f"{url}/api/services/{domain}/{service}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"entity_id": entity_id},
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return f"Home Assistant: {service} → {entity_id} done."
    except requests.exceptions.ConnectionError:
        return f"Could not reach Home Assistant at {url}."
    except requests.exceptions.Timeout:
        return "Home Assistant did not respond in time."
    except requests.exceptions.HTTPError as e:
        return f"Home Assistant rejected the request: {e}"
    except Exception as e:
        return f"Home Assistant error: {e}"


def home_assistant_state(entity_id: str) -> str:
    url, token = _ha_conf()
    if not url or not token:
        return "Home Assistant not configured (set 'home_assistant_url' and 'home_assistant_token')."
    try:
        r = requests.get(
            f"{url}/api/states/{entity_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        return f"{entity_id}: {data.get('state', '?')}"
    except requests.exceptions.ConnectionError:
        return f"Could not reach Home Assistant at {url}."
    except requests.exceptions.HTTPError:
        return f"Entity not found: {entity_id}"
    except Exception as e:
        return f"Home Assistant error: {e}"


def manage_game_server(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    parameters:
        server_name : configured profile name, e.g. 'minecraft' (required for
                      start/stop/status; ignored for 'list' and 'ha_*' actions)
        action      : start | stop | restart | status | list |
                      ha_call | ha_state (required)
        confirm     : bool, required to stop when multiple processes share the name
        entity_id   : Home Assistant entity id (for ha_call / ha_state)
        service     : Home Assistant service, e.g. 'turn_on' (for ha_call)
    """
    params      = parameters or {}
    server_name = params.get("server_name", "")
    action      = params.get("action", "").lower().strip()
    confirm     = bool(params.get("confirm", False))

    if player:
        player.write_log(f"[GameServer] {action} {server_name}")

    try:
        if action == "start":
            return start_game_server(server_name)

        if action == "stop":
            return stop_game_server(server_name, confirm=confirm)

        if action == "restart":
            stop_result = stop_game_server(server_name, confirm=confirm)
            if "processes named" in stop_result or stop_result.startswith("Refusing"):
                return stop_result
            time.sleep(1.0)
            return f"{stop_result}\n{start_game_server(server_name)}"

        if action == "status":
            return status_game_server(server_name)

        if action == "list":
            return list_game_servers()

        if action == "ha_call":
            return home_assistant_call(params.get("entity_id", ""), params.get("service", "toggle"))

        if action == "ha_state":
            return home_assistant_state(params.get("entity_id", ""))

        return f"Unknown manage_game_server action: '{action}'"

    except Exception as e:
        return f"manage_game_server failed: {e}"
