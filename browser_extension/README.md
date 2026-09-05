# Jarvis Browser Bridge

Local Node.js server + Chrome extension that let Jarvis drive a browser in
two ways:

- **Puppeteer window** (`server.js`) — a dedicated, automated Chrome window
  for `SEARCH_AND_CLICK`, `TYPE_TEXT`, `GOTO` commands.
- **Direct tab control** (the extension) — `DIRECT_TYPE_TEXT` / `DIRECT_CLICK`
  act on your *actual* active Chrome tab via `chrome.scripting`, relayed
  through the same server.

Every connection to the bridge (extension included) requires a shared
secret token — there is no unauthenticated control channel. Without a
token, any web page open in any browser on the machine could open a plain
`new WebSocket('ws://localhost:8080')` and drive your browser.

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

| action              | params              | runs where                    |
|---------------------|---------------------|--------------------------------|
| `SEARCH_AND_CLICK`  | `query`             | Puppeteer window (Google search, clicks first organic result) |
| `TYPE_TEXT`         | `selector`, `text`  | Puppeteer window |
| `GOTO`              | `url` (http/https)  | Puppeteer window |
| `DIRECT_TYPE_TEXT`  | `selector`, `text`  | your active Chrome tab, via the extension |
| `DIRECT_CLICK`      | `selector`          | your active Chrome tab, via the extension |

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
