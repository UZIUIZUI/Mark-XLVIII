# Jarvis Bridge

The one unified Node service — combines what used to be three separate
bridges (`browser_extension/`, `whatsapp_bridge/`, `memory_bridge/`) into a
single process with one shared persona, one shared memory, and one token.

This is optional and separate from the main Python app — you don't need it
for Jarvis's voice assistant to work. It exists to give the Chrome
extension and WhatsApp a persistent memory of their own, and to let
WhatsApp trigger browser actions and memory lookups directly.

## What it can do

- **Browser automation** — a dedicated Puppeteer window: search & click,
  type into fields, navigate, run shell commands, mouse/keyboard (via the
  optional `robotjs`), plus `DIRECT_*` commands relayed to the Chrome
  extension to act on your actual active tab.
- **WhatsApp** — send/receive text and files; only your own number can
  issue commands. Message it "merke dir: X ist Y", "was weißt du über X",
  "suche X", or "öffne https://..." and it handles memory/browser actions
  directly — no separate services to wire together, it's all one process.
- **Memory** — SQLite-backed long-term facts + a short-term conversation
  window, shared by the browser side and WhatsApp.
- **SafetyGuard** — `SHELL_EXEC`, file writes/deletes, purchases, and form
  submits always require an explicit "j" typed into this process's own
  terminal before anything runs.

## Setup

**Windows:** double-click `Start_JarvisBridge.bat`. It installs
dependencies, generates a token, optionally asks for your WhatsApp number
(leave blank to skip WhatsApp), and starts the bridge.

**Manual:**
```bash
cd jarvis_bridge
npm install
export JARVIS_TOKEN=$(node -e "console.log(require('crypto').randomBytes(24).toString('hex'))")
export JARVIS_WA_OWNER_NUMBER="015568810689"   # optional, omit to disable WhatsApp
node server.js
```

Load the Chrome extension from `jarvis_bridge/extension/` via
`chrome://extensions` → Developer mode → Load unpacked, then paste the
token from `bridge_token.txt` into its popup.

## Ports

| | port | env var |
|---|---|---|
| Browser WebSocket | `8080` | `JARVIS_WS_PORT` |
| HTTP API | `3000` | `JARVIS_HTTP_PORT` |

## HTTP API

All endpoints require `Authorization: Bearer <JARVIS_TOKEN>`.

```bash
curl http://localhost:3000/status -H "Authorization: Bearer $JARVIS_TOKEN"

curl -X POST http://localhost:3000/command -H "Authorization: Bearer $JARVIS_TOKEN" \
  -H "Content-Type: application/json" -d '{"action":"SEARCH_AND_CLICK","payload":{"query":"jarvis ai"}}'

curl -X POST http://localhost:3000/facts -H "Authorization: Bearer $JARVIS_TOKEN" \
  -H "Content-Type: application/json" -d '{"key":"download_folder","value":"D:/Jarvis/Data"}'

# Only available when JARVIS_WA_OWNER_NUMBER is set:
curl -X POST http://localhost:3000/send-text -H "Authorization: Bearer $JARVIS_TOKEN" \
  -H "Content-Type: application/json" -d '{"to":"015568810689","text":"Hallo, Sir."}'
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `JARVIS_TOKEN` | — (required) | Shared secret for the WebSocket, HTTP API, and Chrome extension |
| `JARVIS_WS_PORT` | `8080` | Browser bridge WebSocket |
| `JARVIS_HTTP_PORT` | `3000` | Unified HTTP API |
| `JARVIS_USER_NAME` | `Sir` | How the persona addresses you |
| `JARVIS_BRIDGE_TTS_VOICE` | `Hedda` | OS TTS voice |
| `JARVIS_BRIDGE_TTS_SPEED` | `1.0` | TTS speed |
| `JARVIS_BRIDGE_VOICE` | on | `off` disables voice feedback |
| `JARVIS_WA_OWNER_NUMBER` | — | Set to enable WhatsApp; your own number |
| `JARVIS_WA_COUNTRY_CODE` | `49` | Prefix used for numbers with a leading 0 |
| `JARVIS_WA_MAX_FILE_MB` | `25` | Reject incoming WhatsApp media larger than this |

## Relationship to the Python app

Separate from `memory/memory_manager.py` (the voice assistant's own
memory) and `actions/browser_control.py` (Playwright automation used
directly by the assistant). This bridge is the Node-side control surface
— a Chrome extension and WhatsApp — with its own notebook. The two systems
don't share facts automatically; if you want that, have a Python action
call this bridge's HTTP API, or vice versa.
