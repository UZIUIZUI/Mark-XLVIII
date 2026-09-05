# Jarvis Browser Bridge

Local Node.js server + Chrome extension that let Jarvis drive a browser in
two ways:

- **Puppeteer window** (`server.js`) — a dedicated, automated Chrome window
  for `SEARCH_AND_CLICK`, `TYPE_TEXT`, `GOTO` commands.
- **Direct tab control** (the extension) — `DIRECT_TYPE_TEXT` / `DIRECT_CLICK`
  act on your *actual* active Chrome tab via `chrome.scripting`, relayed
  through the same server.

A third path, `SHELL_EXEC`, runs arbitrary OS shell commands — gated by the
`SafetyGuard` (below) so nothing executes without an explicit "j" typed
into the server's own terminal, in addition to the token requirement.

Every connection to the bridge (extension included) requires a shared
secret token — there is no unauthenticated control channel. Without a
token, any web page open in any browser on the machine could open a plain
`new WebSocket('ws://localhost:8080')` and drive your browser — and, given
`SHELL_EXEC`'s power, that would mean arbitrary command execution, not just
browser automation. The terminal-approval gate on risky commands does not
replace the token — both apply.

## Setup

1. Install dependencies:
   ```bash
   cd browser_extension
   npm install
   ```

2. Generate a token and start the server:
   ```bash
   export JARVIS_BRIDGE_TOKEN=$(node -e "console.log(require('crypto').randomBytes(24).toString('hex'))")
   echo "Token: $JARVIS_BRIDGE_TOKEN"
   node server.js
   ```
   (On Windows PowerShell: `$env:JARVIS_BRIDGE_TOKEN = node -e "console.log(require('crypto').randomBytes(24).toString('hex'))"`)

3. Load the extension:
   - Open `chrome://extensions`
   - Enable "Developer mode" (top right)
   - Click "Load unpacked" and select the `browser_extension/extension` folder
   - Click the extension's toolbar icon, paste the token from step 2, and save

4. Test the Puppeteer path by sending a command to the bridge, e.g. with
   `wscat` (`npm install -g wscat`):
   ```bash
   wscat -c "ws://localhost:8080?token=$JARVIS_BRIDGE_TOKEN"
   > {"action":"SEARCH_AND_CLICK","query":"jarvis ai assistant"}
   ```

5. Test the direct-tab path (acts on your actual active Chrome tab):
   ```bash
   wscat -c "ws://localhost:8080?token=$JARVIS_BRIDGE_TOKEN"
   > {"action":"DIRECT_TYPE_TEXT","selector":"input[name=q]","text":"hello"}
   ```

## Commands

Send either shape — `{"action": "...", ...params}` or `{"type": "...", "payload": {...}}` —
both are accepted; `description` is optional and shown in the approval prompt for risky commands.

| action / type          | params              | runs where                    | needs approval? |
|------------------------|---------------------|--------------------------------|:---:|
| `SEARCH_AND_CLICK` / `BROWSER_SEARCH_AND_CLICK` | `query` | Puppeteer window (Google search, clicks first organic result, auto-accepts cookie banners) | no |
| `TYPE_TEXT`            | `selector`, `text`  | Puppeteer window | no |
| `GOTO` / `BROWSER_NAVIGATE` | `url` (http/https) | Puppeteer window | no |
| `MOUSE_CLICK`          | `x`, `y`            | OS-level, via `robotjs` (optional dependency) | no |
| `KEYBOARD_TYPE`        | `text`              | OS-level, via `robotjs` (optional dependency) | no |
| `SHELL_EXEC`           | `command`           | a real shell (`child_process.exec`, 30s timeout) | **yes, always** |
| `DIRECT_TYPE_TEXT`     | `selector`, `text`  | your active Chrome tab, via the extension | no |
| `DIRECT_CLICK`         | `selector`          | your active Chrome tab, via the extension | no |

`MOUSE_CLICK`/`KEYBOARD_TYPE` are here for Node-side callers; the Python
Jarvis app already has full mouse/keyboard control via
`actions/computer_control.py` and doesn't need this bridge for that.

## Safety Guard — approval for risky commands

`safety_guard.js` (`SafetyGuard`) decides which commands run immediately
and which require an explicit "j"/"ja" typed into the server's own
terminal before anything happens — voice/WebSocket alone can never
authorize these:

- `SHELL_EXEC`, `FILE_DELETE`, `FILE_WRITE`, `BROWSER_PURCHASE`,
  `BROWSER_SUBMIT_FORM` are **always** treated as risky, whatever their payload.
- Any other command whose JSON payload matches a destructive pattern
  (`rm -rf`, `format`, `shutdown`, `sudo`, `drop table`, `.exe`/`.bat`, ...)
  is risky too.
- On a risky command: the persona asks for permission out loud, then the
  server prompts `[JARVIS PROMPT] "<description>" freigeben? (j/n):` on
  its own stdin. Only "j"/"ja"/"y"/"yes" proceeds; anything else — or a
  closed connection — cancels the action and nothing runs. Concurrent
  risky commands are queued one at a time so two prompts never collide on
  the same terminal.

Example — this will NOT run until you type `j` in the server's terminal:
```json
{"type": "SHELL_EXEC", "payload": {"command": "dir"}, "description": "Dateisystem auflisten"}
```

## Voice feedback

`persona.js` (`JarvisPersona`) gives the bridge its own dry, film-accurate
German voice lines for greeting, acknowledging, completing, and failing a
command — randomly picked per category so it doesn't repeat verbatim every
time. It speaks via the local `say` npm package (OS built-in TTS — SAPI on
Windows, `say`/AVSpeechSynthesizer on macOS, `festival`/`espeak` on Linux).
This is independent of Jarvis's own voice pipeline (`core/tts.py`) — it's
the bridge's own, separate voice.

Configure it with environment variables:
```bash
JARVIS_USER_NAME="Sir"        # how the persona addresses you
JARVIS_BRIDGE_TTS_VOICE=Hedda # OS voice name (Windows SAPI voice, e.g. "Hedda" for German)
JARVIS_BRIDGE_TTS_SPEED=1.0
JARVIS_BRIDGE_VOICE=off       # disable voice entirely
```

## Notes

- This is a standalone peripheral, separate from Jarvis's Python
  `actions/browser_control.py` (which already automates a real browser
  profile directly via Playwright, with no separate Node process needed).
  Use this bridge specifically when you want a Chrome-extension-driven
  control path instead.
- The Puppeteer window is a separate Chrome instance from your everyday
  browser — it does not see your logins/tabs. Use the `DIRECT_*` commands
  through the extension when you need to act on your real, already-open tab.
- Rotate the token by generating a new one and updating both the server's
  environment variable and the extension popup.
