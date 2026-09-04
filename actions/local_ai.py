#local_ai.py
"""
Local AI backends — Ollama, LM Studio (OpenAI-compatible), and offline
Whisper file transcription. No cloud calls; everything here talks to
processes running on the same machine.
"""
import sys
import json
from pathlib import Path

import requests

_REQUEST_TIMEOUT = 30


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


def _ollama_url() -> str:
    return _load_config().get("ollama_url", "http://localhost:11434").rstrip("/")


def _lmstudio_url() -> str:
    return _load_config().get("lmstudio_url", "http://localhost:1234").rstrip("/")


# ── Ollama ────────────────────────────────────────────────────────────────

def ollama_list_models() -> str:
    try:
        r = requests.get(f"{_ollama_url()}/api/tags", timeout=_REQUEST_TIMEOUT)
        r.raise_for_status()
        models = [m.get("name", "?") for m in r.json().get("models", [])]
        if not models:
            return "Ollama is running but no models are installed. Run: ollama pull <model>"
        return "Installed Ollama models:\n" + "\n".join(f"  - {m}" for m in models)
    except requests.exceptions.ConnectionError:
        return f"Could not reach Ollama at {_ollama_url()} — is 'ollama serve' running?"
    except requests.exceptions.Timeout:
        return "Ollama did not respond in time."
    except Exception as e:
        return f"Ollama error: {e}"


def ollama_generate(model: str, prompt: str) -> str:
    if not model:
        return "No Ollama model specified."
    if not prompt:
        return "No prompt provided."
    try:
        r = requests.post(
            f"{_ollama_url()}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=120,
        )
        r.raise_for_status()
        text = r.json().get("response", "").strip()
        return text or "Ollama returned an empty response."
    except requests.exceptions.ConnectionError:
        return f"Could not reach Ollama at {_ollama_url()} — is 'ollama serve' running?"
    except requests.exceptions.Timeout:
        return f"Ollama model '{model}' timed out after 120s."
    except requests.exceptions.HTTPError as e:
        return f"Ollama rejected the request (model '{model}' installed?): {e}"
    except Exception as e:
        return f"Ollama error: {e}"


# ── LM Studio (OpenAI-compatible local server) ──────────────────────────────

def lmstudio_list_models() -> str:
    try:
        r = requests.get(f"{_lmstudio_url()}/v1/models", timeout=_REQUEST_TIMEOUT)
        r.raise_for_status()
        models = [m.get("id", "?") for m in r.json().get("data", [])]
        if not models:
            return "LM Studio is running but reports no loaded models."
        return "LM Studio models:\n" + "\n".join(f"  - {m}" for m in models)
    except requests.exceptions.ConnectionError:
        return f"Could not reach LM Studio at {_lmstudio_url()} — is the local server started?"
    except requests.exceptions.Timeout:
        return "LM Studio did not respond in time."
    except Exception as e:
        return f"LM Studio error: {e}"


def lmstudio_generate(model: str, prompt: str) -> str:
    if not prompt:
        return "No prompt provided."
    try:
        r = requests.post(
            f"{_lmstudio_url()}/v1/chat/completions",
            json={
                "model": model or "local-model",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            },
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"].strip()
        return text or "LM Studio returned an empty response."
    except requests.exceptions.ConnectionError:
        return f"Could not reach LM Studio at {_lmstudio_url()} — is the local server started?"
    except requests.exceptions.Timeout:
        return "LM Studio timed out after 120s."
    except (KeyError, IndexError):
        return "LM Studio returned an unexpected response shape."
    except Exception as e:
        return f"LM Studio error: {e}"


# ── Offline Whisper file transcription ──────────────────────────────────────

_whisper_model_cache: dict = {}


def transcribe_audio_file(file_path: str, model_size: str = "base") -> str:
    if not file_path:
        return "No audio file path provided."

    path = Path(file_path).expanduser()
    if not path.exists():
        return f"Audio file not found: {file_path}"
    if not path.is_file():
        return f"Not a file: {file_path}"

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return "faster-whisper is not installed. Run: pip install faster-whisper"

    try:
        model = _whisper_model_cache.get(model_size)
        if model is None:
            try:
                import torch
                device  = "cuda" if torch.cuda.is_available() else "cpu"
                compute = "float16" if device == "cuda" else "int8"
            except Exception:
                device, compute = "cpu", "int8"
            model = WhisperModel(model_size, device=device, compute_type=compute)
            _whisper_model_cache[model_size] = model

        segments, _ = model.transcribe(str(path), beam_size=1, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text or "(no speech detected in file)"
    except Exception as e:
        return f"Transcription failed: {e}"


# ── Public entry point ───────────────────────────────────────────────────────

def run_local_model(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    parameters:
        backend : ollama | lmstudio (default: ollama)
        action  : generate | list_models | transcribe_file (default: generate)
        model   : model name (backend-specific)
        prompt  : prompt text for 'generate'
        file_path    : audio file path for 'transcribe_file'
        model_size   : whisper model size for 'transcribe_file' (default: base)
    """
    params  = parameters or {}
    backend = params.get("backend", "ollama").lower().strip()
    action  = params.get("action", "generate").lower().strip()

    if player:
        player.write_log(f"[LocalAI] {backend}:{action}")

    try:
        if action == "transcribe_file":
            return transcribe_audio_file(
                params.get("file_path", ""),
                params.get("model_size", "base"),
            )

        if action == "list_models":
            return lmstudio_list_models() if backend == "lmstudio" else ollama_list_models()

        if action == "generate":
            model  = params.get("model", "")
            prompt = params.get("prompt", "")
            if backend == "lmstudio":
                return lmstudio_generate(model, prompt)
            return ollama_generate(model, prompt)

        return f"Unknown local_ai action: '{action}'"

    except Exception as e:
        return f"run_local_model failed: {e}"
