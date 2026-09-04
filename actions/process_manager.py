#process_manager.py
"""
Process lifecycle management — start/stop/restart/status/list for
arbitrary programs, built on top of psutil and subprocess.
Complements actions/open_app.py (which resolves human-friendly app names);
this module is for starting a specific executable/command and managing the
resulting process by PID or name.
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

from actions.system_monitor import list_processes, kill_process

_START_TIMEOUT = 10  # seconds to confirm a launched process is alive


def start_process(command: str, args: list | None = None, cwd: str | None = None) -> str:
    if not command:
        return "No command specified."

    args = args or []
    resolved = shutil.which(command)
    exe = resolved or command

    try:
        working_dir = str(Path(cwd).expanduser()) if cwd else None
        if working_dir and not Path(working_dir).is_dir():
            return f"Working directory does not exist: {cwd}"

        proc = subprocess.Popen(
            [exe, *args],
            cwd=working_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return f"Executable not found: {command}"
    except PermissionError:
        return f"Permission denied launching: {command}"
    except Exception as e:
        return f"Could not start '{command}': {e}"

    deadline = time.monotonic() + _START_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return f"'{command}' exited immediately (code {proc.returncode})."
        try:
            if psutil.pid_exists(proc.pid):
                return f"Started '{command}' (PID {proc.pid})."
        except Exception:
            pass
        time.sleep(0.2)

    return f"Started '{command}' (PID {proc.pid}) — still running after {_START_TIMEOUT}s check."


def stop_process(name_or_pid: str, confirm: bool = False) -> str:
    return kill_process(name_or_pid, confirm=confirm)


def status_process(name_or_pid: str) -> str:
    name_or_pid = (name_or_pid or "").strip()
    if not name_or_pid:
        return "No process name or PID given."

    matches = []
    try:
        if name_or_pid.isdigit():
            try:
                p = psutil.Process(int(name_or_pid))
                matches = [p]
            except psutil.NoSuchProcess:
                matches = []
        else:
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    if (p.info.get("name") or "").lower() == name_or_pid.lower():
                        matches.append(p)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
    except Exception as e:
        return f"Could not check status: {e}"

    if not matches:
        return f"'{name_or_pid}' is not running."

    lines = [f"'{name_or_pid}' is running ({len(matches)} instance(s)):"]
    for p in matches:
        try:
            with p.oneshot():
                cpu = p.cpu_percent(interval=0.1)
                ram = p.memory_percent()
                status = p.status()
            lines.append(f"  PID {p.pid:>6}  status={status}  CPU {cpu:5.1f}%  RAM {ram:5.1f}%")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            lines.append(f"  PID {p.pid:>6}  (details unavailable)")
    return "\n".join(lines)


def restart_process(command: str, name_or_pid: str, args: list | None = None,
                     cwd: str | None = None, confirm: bool = False) -> str:
    stop_result = stop_process(name_or_pid, confirm=confirm)
    if stop_result.startswith("Refusing") or "processes named" in stop_result:
        return stop_result
    time.sleep(1.0)
    start_result = start_process(command, args=args, cwd=cwd)
    return f"{stop_result}\n{start_result}"


def manage_process(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    parameters:
        action       : start | stop | restart | status | list (required)
        command      : executable name or path (for start/restart)
        args         : list of CLI arguments (optional, for start/restart)
        cwd          : working directory (optional, for start/restart)
        process_name : process name or PID (for stop/restart/status)
        confirm      : bool, required to stop when multiple processes share the name
        sort_by      : cpu | ram (for 'list', default: cpu)
        limit        : max processes to return (for 'list', default: 15)
    """
    params  = parameters or {}
    action  = params.get("action", "").lower().strip()
    target  = params.get("process_name", "") or params.get("target", "")
    confirm = bool(params.get("confirm", False))

    if player:
        player.write_log(f"[Process] {action} {target}")

    try:
        if action == "start":
            return start_process(
                params.get("command", ""),
                args=params.get("args"),
                cwd=params.get("cwd"),
            )

        if action == "stop":
            return stop_process(target, confirm=confirm)

        if action == "restart":
            return restart_process(
                params.get("command", ""),
                target,
                args=params.get("args"),
                cwd=params.get("cwd"),
                confirm=confirm,
            )

        if action == "status":
            return status_process(target)

        if action == "list":
            return list_processes(
                sort_by=params.get("sort_by", "cpu"),
                limit=int(params.get("limit", 15)),
            )

        return f"Unknown manage_process action: '{action}'"

    except Exception as e:
        return f"manage_process failed: {e}"
