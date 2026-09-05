# Jarvis WhatsApp Bridge

A `whatsapp-web.js` client that lets Jarvis send/receive WhatsApp text and
files programmatically, plus a small token-gated HTTP API so the Python
Jarvis app can trigger sends. This is a more reliable alternative to
`actions/send_message.py`'s WhatsApp path, which drives the WhatsApp
Desktop app via `pyautogui` UI automation.

## Setup

1. Install dependencies:
   ```bash
   cd whatsapp_bridge
   npm install
   ```

2. Set required environment variables:
   ```bash
   export JARVIS_WA_OWNER_NUMBER="015568810689"   # your own number
   export JARVIS_WA_HTTP_TOKEN=$(node -e "console.log(require('crypto').randomBytes(24).toString('hex'))")
   echo "HTTP token: $JARVIS_WA_HTTP_TOKEN"
   ```
   `JARVIS_WA_OWNER_NUMBER` is required — the bridge refuses to start
   without it, since without a fixed owner number there would be no way to
   tell "you" apart from any other WhatsApp contact.

   `JARVIS_WA_HTTP_TOKEN` is optional but recommended: without it the
   HTTP API simply stays disabled (the WhatsApp client itself still runs).

3. Start it:
   ```bash
   node JarvisWhatsApp.js
   ```

4. Scan the QR code shown in the terminal with WhatsApp → Linked Devices.
   The session is cached locally (`.wwebjs_auth/`, gitignored) so future
   starts don't need a re-scan.

## Security model

- **Only your own chat can issue commands.** A message is only ever acted
  on when it comes from `JARVIS_WA_OWNER_NUMBER`'s own JID. Any other
  sender's messages are logged but never trigger file saves or replies —
  a "starts with jarvis" check on *any* sender (as in an earlier draft of
  this) would let any WhatsApp contact make the bot write files to your
  disk and send messages from your own account.
- **Incoming media has a size cap** (`JARVIS_WA_MAX_FILE_MB`, default 25MB)
  — oversized files are rejected instead of written to disk.
- **The HTTP API requires a bearer token** (`JARVIS_WA_HTTP_TOKEN`) on
  every request, the same shared-secret pattern as `browser_extension/`.

## HTTP API

All endpoints require `Authorization: Bearer <JARVIS_WA_HTTP_TOKEN>`.

```bash
curl -X POST http://localhost:3100/send-text \
  -H "Authorization: Bearer $JARVIS_WA_HTTP_TOKEN" -H "Content-Type: application/json" \
  -d '{"to": "015568810689", "text": "System-Test erfolgreich."}'

curl -X POST http://localhost:3100/send-file \
  -H "Authorization: Bearer $JARVIS_WA_HTTP_TOKEN" -H "Content-Type: application/json" \
  -d '{"to": "015568810689", "filePath": "/absolute/path/to/file.pdf", "caption": "Hier, Sir."}'

curl http://localhost:3100/status -H "Authorization: Bearer $JARVIS_WA_HTTP_TOKEN"
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `JARVIS_WA_OWNER_NUMBER` | — (required) | Your number; digits, or with leading 0/+ |
| `JARVIS_WA_COUNTRY_CODE` | `49` | Prefix used when a number starts with a leading 0 |
| `JARVIS_WA_HTTP_TOKEN` | — | Enables the HTTP API when set |
| `JARVIS_WA_HTTP_PORT` | `3100` | HTTP API port |
| `JARVIS_WA_MAX_FILE_MB` | `25` | Reject incoming media larger than this |
| `JARVIS_USER_NAME` | `Sir` | How the shared persona addresses you |
| `JARVIS_BRIDGE_TTS_VOICE` | `Hedda` | OS TTS voice (shared with `browser_extension/`) |
| `JARVIS_BRIDGE_VOICE` | on | Set to `off` to disable voice feedback |

## Notes

- Uses the same `JarvisPersona` as `browser_extension/persona.js`
  (`../browser_extension/persona.js`) rather than a second, separate voice
  implementation.
- `whatsapp-web.js` runs its own bundled Puppeteer/Chromium under the hood
  (headless) — no separate browser window like `browser_extension/`'s
  Puppeteer bridge.
