#render_jobs.py
"""
Real Blender headless-render jobs via the Blender CLI (`blender -b ... `).
Jobs run in a background thread so the render_job tool call returns
immediately; use action='status' to poll progress.

Blender executable path is auto-detected via PATH, or configured in
config/api_keys.json as "blender_path".
"""
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

_MAX_RENDER_SECONDS = 3600  # hard cap so a runaway render can't hang forever
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


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


def _blender_exe() -> str | None:
    configured = _load_config().get("blender_path", "")
    if configured and Path(configured).exists():
        return configured
    return shutil.which("blender")


_FORMAT_FLAGS = {
    "png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "tiff": "TIFF",
    "mp4": "FFMPEG", "avi": "AVI_JPEG", "mkv": "FFMPEG",
}


def _run_job(job_id: str, blender_exe: str, project_path: Path,
             output_path: Path, output_format: str, frame_range: str | None):
    job = _jobs[job_id]
    args = [
        blender_exe, "-b", str(project_path),
        "-o", str(output_path / "frame_"),
    ]

    blender_format = _FORMAT_FLAGS.get(output_format.lower())
    if blender_format:
        args += ["-F", blender_format]

    if frame_range:
        try:
            if "-" in frame_range:
                start, end = frame_range.split("-", 1)
                args += ["-s", start.strip(), "-e", end.strip(), "-a"]
            else:
                args += ["-f", frame_range.strip()]
        except Exception:
            args += ["-a"]
    else:
        args += ["-a"]

    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        job["pid"] = proc.pid
        job["status"] = "running"

        deadline = time.monotonic() + _MAX_RENDER_SECONDS
        last_line = ""
        for line in proc.stdout:
            last_line = line.strip()
            match = re.search(r"Fra:(\d+)", last_line)
            if match:
                job["last_frame"] = match.group(1)
            if time.monotonic() > deadline:
                proc.kill()
                job["status"] = "timed_out"
                job["error"] = f"Exceeded {_MAX_RENDER_SECONDS}s render limit."
                return

        returncode = proc.wait()
        if returncode == 0:
            job["status"] = "done"
            job["output"] = str(output_path)
        else:
            job["status"] = "failed"
            job["error"] = f"Blender exited with code {returncode}: {last_line[:200]}"

    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)


def trigger_render_job(project_path: str, output_format: str = "png",
                        frame_range: str | None = None) -> str:
    if not project_path:
        return "No project path provided."

    blender_exe = _blender_exe()
    if not blender_exe:
        return (
            "Blender executable not found. Install Blender and ensure it's on "
            "PATH, or set 'blender_path' in config/api_keys.json."
        )

    src = Path(project_path).expanduser()
    if not src.exists():
        return f"Project file not found: {project_path}"
    if src.suffix.lower() != ".blend":
        return f"Expected a .blend file, got: {src.suffix}"

    output_dir = src.parent / f"{src.stem}_render"
    try:
        output_dir.mkdir(exist_ok=True)
    except Exception as e:
        return f"Could not create output directory: {e}"

    job_id = uuid.uuid4().hex[:8]
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "starting", "project": str(src),
            "output_format": output_format, "pid": None,
            "last_frame": None, "error": None,
        }

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, blender_exe, src, output_dir, output_format, frame_range),
        daemon=True,
    )
    thread.start()

    return f"Render job started: {job_id} (project: {src.name}). Check with action='status', job_id='{job_id}'."


def render_job_status(job_id: str) -> str:
    if not job_id:
        with _jobs_lock:
            if not _jobs:
                return "No render jobs have been started."
            lines = ["Render jobs:"]
            for jid, job in _jobs.items():
                lines.append(f"  {jid}: {job['status']}" + (f" (frame {job['last_frame']})" if job.get("last_frame") else ""))
            return "\n".join(lines)

    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return f"No render job with id '{job_id}'."

    status = job["status"]
    if status == "running":
        frame = f" (last frame: {job['last_frame']})" if job.get("last_frame") else ""
        return f"Job {job_id}: rendering{frame}."
    if status == "done":
        return f"Job {job_id}: done. Output: {job['output']}"
    if status in ("failed", "timed_out"):
        return f"Job {job_id}: {status}. {job.get('error', '')}"
    return f"Job {job_id}: {status}."


def cancel_render_job(job_id: str) -> str:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return f"No render job with id '{job_id}'."
    pid = job.get("pid")
    if not pid or job["status"] not in ("starting", "running"):
        return f"Job {job_id} is not currently running."
    try:
        import psutil
        psutil.Process(pid).terminate()
        job["status"] = "cancelled"
        return f"Job {job_id} cancelled."
    except Exception as e:
        return f"Could not cancel job {job_id}: {e}"


def render_job_action(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    parameters:
        action        : start | status | cancel (default: start)
        project_path  : path to a .blend file (required for 'start')
        output_format : png | jpg | tiff | mp4 | avi | mkv (default: png)
        frame_range   : single frame, e.g. '10', or a range 'start-end' for an
                        animation; omit to render the full animation
        job_id        : job id returned by 'start' (required for status/cancel;
                        omit for 'status' to list all jobs)
    """
    params = parameters or {}
    action = params.get("action", "start").lower().strip()

    if player:
        player.write_log(f"[Render] {action}")

    try:
        if action == "start":
            return trigger_render_job(
                params.get("project_path", ""),
                output_format=params.get("output_format", "png"),
                frame_range=params.get("frame_range"),
            )

        if action == "status":
            return render_job_status(params.get("job_id", ""))

        if action == "cancel":
            return cancel_render_job(params.get("job_id", ""))

        return f"Unknown render_job action: '{action}'"

    except Exception as e:
        return f"render_job_action failed: {e}"
