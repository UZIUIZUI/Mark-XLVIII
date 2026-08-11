# CLAUDE.md

Guidance for AI assistants working in this repository.

## What this project is

**MARK XLVIII** is a desktop voice assistant ("JARVIS") built on the **Gemini Live API**
(native audio, bidirectional streaming). It listens on the microphone, speaks back through
the speakers, sees the screen/webcam on demand, and controls the host computer through a set
of ~19 function-calling tools. A PyQt6 HUD renders the waveform, logs, system metrics, and a
file drop zone. An optional FastAPI dashboard exposes the same assistant to a phone on the LAN.

Single-user desktop app — **not a library, not a service**. There is no test suite, no linter
config, no CI, and no packaging metadata. `setup.py` is a dependency installer script, *not* a
setuptools file (despite the name).

- Python **3.11+ required** (`asyncio.TaskGroup`, `X | Y` unions at runtime).
- Cross-platform: Windows / macOS / Linux, with per-OS branches inside most action modules.
- Licensed CC BY-NC 4.0 (personal, non-commercial).

## Running it

```bash
pip install -r requirements.txt   # or: python setup.py  (also runs `playwright install`)
python main.py
```

On first launch the UI shows a setup overlay that asks for a Gemini API key and OS, then writes
`config/api_keys.json`. Nothing runs before that file exists — `main()` blocks in
`ui.wait_for_api_key()` until the overlay is submitted.

**Known dependency gaps** (the readme acknowledges this — install on `ModuleNotFoundError`):
`requirements.txt` does **not** list `PyQt6`, even though `ui.py` cannot import without it.
`duckduckgo-search` is listed but `web_search.py` prefers the newer `ddgs` package and falls
back. Optional/heavy imports (`cv2`, `mss`, `PIL`, `pyautogui`, `fastapi`, `pycaw`, …) are
guarded by `try/except ImportError` with a module-level `_FLAG` boolean; keep that pattern —
a missing optional dep must degrade a feature, never crash startup.

There is **no `.gitignore`**. Before committing, check that you are not adding
`config/api_keys.json` (API key), `memory/long_term.json` (personal data), or `uploads/`.

## Files that are not in the repo but exist at runtime

| Path | Created by | Contents |
|---|---|---|
| `config/api_keys.json` | UI setup overlay (`ui.py:2361`), `memory/config_manager.py` | `gemini_api_key`, `os_system`, `camera_index` (auto-probed by `screen_processor`) |
| `memory/long_term.json` | `memory/memory_manager.py` | Six-category long-term memory |
| `face.png` | — | Optional HUD avatar; `main()` passes the name unconditionally, `HudCanvas._load_face` swallows the failure |
| `~/Downloads/JARVIS Uploads/` | `dashboard/server.py` | Phone uploads |

`config/certs/jarvis.{key,crt}` **are** committed — a self-signed cert for the LAN dashboard.
Their presence is what flips the dashboard from HTTP to HTTPS (`DashboardServer._ssl_enabled`).
Treat the key as public/compromised; it is not a secret worth protecting, but do not generate
new secrets into the repo.

## Architecture

```
main.py     ── JarvisLive: Gemini Live session, audio I/O, tool dispatch, background loops
ui.py       ── PyQt6 HUD (MainWindow) + thread-safe JarvisUI facade
actions/    ── one module per tool; plain blocking functions
core/       ── prompt.txt (live) + stt/tts/llm_client/installer (DORMANT, see below)
memory/     ── JSON long-term memory + api_keys.json read/write
dashboard/  ── FastAPI LAN server + static phone UI (login.html / app.html)
config/     ── OS detection helpers, icon, TLS certs
```

### Threading model — the single most important thing to understand

```
Qt main thread                     background daemon thread
──────────────                     ────────────────────────
ui.root.mainloop()                 asyncio.run(JarvisLive.run())
(QApplication.exec)                  ├── _send_realtime   → mic PCM → Gemini
                                     ├── _listen_audio    (sounddevice callback thread → loop)
                                     ├── _receive_audio   ← audio / transcripts / tool_call
                                     ├── _play_audio      → speakers
                                     ├── _run_system_monitor   (10 s)
                                     ├── _run_proactive_mode   (60 s)
                                     └── _relay_phone_audio    (dashboard)
```

Consequences you must respect:

- **Never touch Qt widgets from the asyncio thread.** Go through the `JarvisUI` facade
  (`ui.py:2383`), whose methods emit Qt signals (`_log_sig`, `_state_sig`, `_content_sig`,
  `_camera_sig`, `_reconfig_sig`). Action modules receive this facade as `player`.
- **Action functions are blocking and synchronous.** `_execute_tool` wraps every one in
  `loop.run_in_executor(None, lambda: fn(...))`. Do not make them `async`.
- The whole `run()` body is an infinite reconnect loop wrapped in `except BaseException` —
  `TaskGroup` raises `BaseExceptionGroup`, which `except Exception` would miss and let escape,
  killing the loop. Keep that catch broad.
- Reconnect backoff is exponential 3→6→12→60 s for network errors; an invalid API key
  (`"API key not valid"` / `"1007"`) instead re-opens the setup overlay and waits.

### Tool-call flow

1. Gemini emits `response.tool_call` → `_receive_audio` calls `_execute_tool(fc)` per call.
2. `_execute_tool` is one long `if name == ... elif ...` chain (`main.py:649`). Each branch
   runs the action in the executor and coerces the result to a string.
3. All branches are wrapped in a single `try/except`; failures become
   `"Tool 'x' failed: …"` and additionally trigger `speak_error` (spoken apology).
4. The string is returned as `types.FunctionResponse(response={"result": result})` — **Gemini
   reads this text and paraphrases it aloud**. That is why action return values are short,
   natural, first-person English sentences, not JSON or logs.

Two branches break the pattern deliberately:
- `save_memory` returns early with `{"result": "ok", "silent": True}` — never spoken.
- `shutdown_jarvis` spawns a thread that calls `os._exit(0)` after 1 s.

### Vision is a two-turn dance (don't "simplify" it)

`screen_process` cannot return an image through a function response, so:

1. The tool captures the image, stashes it in `self._pending_vision`, and returns a
   `[VISION_ACTIVE]` instruction telling Gemini to *immediately* say one filler sentence
   ("Looking at your screen now, sir") without guessing content.
2. On the next `turn_complete`, `_receive_audio` injects the image as
   `send_client_content(inline_data + question)` — a separate user turn.
3. For camera captures, `_vision_close_pending` defers closing the live preview until the
   answer turn completes (+2 s).

Guards: `_vision_busy` flag and a 4 s `_vision_last_time` cooldown block echo-triggered
duplicate calls (JARVIS hearing itself say "screen"). All vision/interrupt flags are reset on
every reconnect inside `run()` — a stale flag from a crashed session used to wedge the assistant.

### Interrupt path

`ui.py` binds **Escape** and the INTERRUPT button to `JarvisLive.interrupt()`. Incoming audio is
sliced into 2400-byte (~50 ms @ 24 kHz) chunks in `_receive_audio` precisely so draining
`audio_in_queue` lands within one slice. `_interrupted` stays set until the matching
`turn_complete`, which discards the buffered transcripts for that turn.

### Audio constants

Mic 16 kHz in / speaker 24 kHz out, mono int16, 1024-frame blocks. The mic callback drops
frames while `_is_speaking` (guarded by `_speaking_lock`), while muted, or while
`_phone_active` (phone mic takes over).

## Adding a new tool

Four edits, all mechanical:

1. **`actions/my_tool.py`** — one public function matching the house signature:
   ```python
   def my_tool(parameters: dict, response=None, player=None, session_memory=None) -> str:
       ...
       return "Short spoken-style confirmation, sir."
   ```
   `response` and `session_memory` are legacy and always `None` from `main.py`; keep them for
   consistency. Some tools additionally take `speak=` (a callback that pushes text into the live
   session mid-run, for long operations): `code_helper`, `dev_agent`, `file_processor`,
   `flight_finder`, `game_updater`, `youtube_video`.
2. **`TOOL_DECLARATIONS`** in `main.py:94` — a Gemini function declaration. Types are the
   uppercase Gemini spellings: `"OBJECT"`, `"STRING"`, `"BOOLEAN"`, `"INTEGER"`, `"NUMBER"`,
   `"ARRAY"`. Descriptions are prompt engineering — they carry routing rules
   ("THE ONLY tool for ANY Steam request", "NEVER use browser_control for Steam").
3. **`_execute_tool`** — an `elif name == "my_tool":` branch with `run_in_executor` and an
   `or "Done."` fallback.
4. **Import** at the top of `main.py` (aligned-column import block).

If the tool produces text worth showing on screen, mirror it with
`self.ui.show_content(label, text)` — see the `web_search` branch.

## Conventions in `actions/`

- **Return, never raise.** Catch everything and return an explanatory sentence; the string is
  spoken. Prefix logs with a bracket tag: `print(f"[Settings] …")`, `[Vision]`, `[WebSearch]`.
- **Mirror to the HUD** via `player.write_log(...)`, always behind a `if player:` /
  `try/except` guard — `player` may be `None` when a module is called directly.
- **Path resolution** — every module repeats this PyInstaller-aware helper; copy it rather
  than importing across modules:
  ```python
  def get_base_dir() -> Path:
      if getattr(sys, "frozen", False):
          return Path(sys.executable).parent
      return Path(__file__).resolve().parent.parent
  ```
- **API key** is read fresh from `config/api_keys.json` per call (`_get_api_key()` duplicated in
  ~10 modules). Not cached — the user can re-key at runtime.
- **OS detection has two competing idioms.** `platform.system()` → `"Windows"/"Darwin"/"Linux"`
  (module-level `_OS`), and `config.get_os()` / `is_windows()` → `"windows"/"mac"/"linux"`
  honoring the user's `os_system` override. Match whichever the file already uses.
- **Windows console suppression** is global: `main.py` monkey-patches `subprocess.Popen` at
  import time (before any other import) to force `CREATE_NO_WINDOW`. Modules that may run
  standalone also carry a local `_WIN_HIDE` dict. Don't remove either.
- **Dangerous actions gate on confirmation.** `computer_settings` requires
  `confirmed=yes` for `_DANGEROUS_ACTIONS` (shutdown/restart); `file_controller._is_safe_path`
  blocks writes outside allowed roots. Preserve these guards when editing.
- **Language is mixed by design.** Code, tool descriptions, and spoken defaults are English;
  a few comments and some user-facing status strings are Turkish (e.g. the reconnect message in
  `main.py`, comments in `file_controller.py`). Leave existing Turkish text alone unless the task
  is about it — the assistant is bilingual and the model translates spoken output at runtime.
- **Per-model choices**: `gemini-2.5-flash` for reasoning/summarization, `gemini-2.5-flash-lite`
  for cheap intent classification, `gemini-2.5-flash-native-audio-preview-12-2025` for the live
  session. The live model ID appears in both `main.py:66` and `screen_processor.py:75`.

Several tools (`computer_settings`, `desktop`, `computer_control`) use a secondary Gemini call
as an intent classifier: natural-language `description` → JSON `{action, value}` matched against
an `ACTION_MAP`. That is the intended fallback when `action` is not supplied explicitly.

## Prompting and memory

- `core/prompt.txt` is the live system prompt, prepended with current date/time and a rendered
  memory block in `_build_config()`. Editing it changes runtime behavior — treat it as code.
  It defines tagged channels the code emits: `[SYSTEM_ALERT]` (hardware), `[STARTUP_BRIEFING]`,
  `[PROACTIVE_CHECK]`, plus the address rule (Turkish → "efendim", English → "sir", never mixed).
  Note it still documents an `agent_task` tool that no longer exists in `TOOL_DECLARATIONS`.
- **Memory** (`memory/memory_manager.py`) is a JSON file with six fixed categories:
  `identity`, `preferences`, `projects`, `relationships`, `wishes`, `notes`. Each entry is
  `{"value": str, "updated": "YYYY-MM-DD"}`. Values are truncated at 380 chars and the whole
  file is trimmed oldest-first to stay under 2200 chars, because it is injected into every
  session's system prompt. The model writes to it by calling `save_memory` silently; language
  detection is stored as `identity/language` and drives briefing/greeting language.

## Background behaviors

- **Startup briefing** (`_send_startup_briefing`) fires once per process: phase 1 is a greeting
  with the time; phase 2 (news via `web_search` mode `news`) is dispatched 1.5 s later so it
  overlaps phase-1 playback.
- **System monitor** polls every 10 s; `SystemMonitor.check()` returns a `[SYSTEM_ALERT]` string
  when CPU/RAM/GPU/temperature crosses a threshold (with its own cooldown state).
- **Proactive mode** evaluates every 60 s: after 900 s of user silence (and 600 s since the last
  trigger) it hands time + memory to Gemini and lets the model decide whether to speak.
  No hardcoded rules — see `actions/proactive.py`.

## Remote dashboard (`dashboard/`)

Optional; disabled silently if `fastapi`/`uvicorn`/`cryptography` are missing (`_DEPS_OK`).
Serves on `0.0.0.0:8000` (plus `8001` as an HTTPS alias when certs exist, because Chrome
HTTPS-upgrades bare `IP:PORT` entries). The "Remote Control" button in the HUD mints a 6-char
key (10 min TTL, ambiguous characters excluded) and renders a QR code.

Payloads are AES-256-CBC encrypted client-side with CryptoJS, keyed by
`SHA-256(sessionKey ‖ "JARVIS-DASHBOARD-v1")`; `crypto-js.min.js` is cached into
`dashboard/static/` on first use so no CDN is needed afterwards. It also best-effort opens the
OS firewall (`_ensure_network_access`, elevated per platform) in a background thread.

Bridges into `JarvisLive`: `_command_queue` (typed commands → `send_client_content`),
`_phone_audio_queue` (phone mic PCM → `out_queue`, which mutes the PC mic), and `broadcast()`
(transcripts + status pushed to `/ws`).

## Dormant code — check before editing

`core/stt.py`, `core/tts.py`, `core/llm_client.py`, and `core/installer.py` are leftovers from
**MARK XL** (local Whisper/Vosk STT, EdgeTTS/Kokoro/ElevenLabs TTS, Ollama/LM Studio clients,
an auto-installer). **Nothing imports them** — the Gemini Live session handles STT and TTS
natively. Their docstrings describe config keys (`llm_provider`, `llm_url`, `llm_model`,
`tts_voice`) that no live code reads. Don't wire them back in or "fix" them unless explicitly
asked; do not treat their conventions as current.

## Verification

There are no tests. To check work:

```bash
python -m py_compile main.py ui.py actions/*.py core/*.py memory/*.py dashboard/*.py
```

Action modules can be exercised in isolation, since they are plain functions:

```python
from actions.web_search import web_search
print(web_search({"query": "python 3.13 release", "mode": "news"}))
```

A full run needs a real Gemini API key, a microphone, a display, and (for most action modules)
the host OS the branch targets — say so plainly rather than claiming an untestable change works.

## Git workflow

Default branch is `main`. Commit history is mostly bulk "Add files via upload" — do not imitate
that; write descriptive messages. Push only to the branch you were assigned, and do not open a
pull request unless asked.
