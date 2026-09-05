# Jarvis Memory Bridge

Persistent short-/long-term memory for Jarvis's Node peripherals
(`browser_extension/`, `whatsapp_bridge/`), backed by SQLite
(`jarvis_memory.sqlite`, gitignored — it's local data, not code).

This is **separate** from the main Python app's own memory
(`memory/memory_manager.py`, `memory/long_term.json`), which backs the
voice assistant's conversations directly and already has its own
identity/preferences/projects/relationships/wishes/notes structure. This
bridge is a second, independent notebook for the Node-side peripherals —
it does not read from or write to the Python memory, and the two won't
see each other's facts unless you explicitly wire that up (e.g. having a
Python action call this bridge's HTTP API, or vice versa).

## Setup

1. Install dependencies here, **and** make sure `browser_extension/` has
   also run `npm install` at least once — this bridge reuses
   `browser_extension/persona.js` for voice feedback, and that file's own
   `say` dependency is resolved from `browser_extension/node_modules`,
   not from here:
   ```bash
   cd browser_extension && npm install && cd ../memory_bridge && npm install
   ```

2. Set a token (required — the server refuses to start without one):
   ```bash
   export JARVIS_MEMORY_TOKEN=$(node -e "console.log(require('crypto').randomBytes(24).toString('hex'))")
   ```

3. Start it:
   ```bash
   node server.js
   ```

## Ports

Deliberately different from `browser_extension/`'s WebSocket (8080) and
`whatsapp_bridge/`'s HTTP API (3100) so all three can run at once:

| | default port | env var |
|---|---|---|
| WebSocket | `8090` | `JARVIS_MEMORY_WS_PORT` |
| HTTP API  | `3200` | `JARVIS_MEMORY_HTTP_PORT` |

## WebSocket usage

```bash
wscat -c "ws://localhost:8090?token=$JARVIS_MEMORY_TOKEN"
> {"prompt": "Merke dir: Mein Standard-Download-Ordner ist D:/Jarvis/Data"}
> {"prompt": "Was weißt du über mein Standard-Download-Ordner"}
```

Any other prompt returns the full assembled context (all long-term facts
+ the last 10 short-term turns) instead of just a status line — the
short-term window lives in process memory only and resets when the
server restarts; long-term facts persist in SQLite.

## HTTP API

All endpoints require `Authorization: Bearer <JARVIS_MEMORY_TOKEN>`.

```bash
curl http://localhost:3200/facts -H "Authorization: Bearer $JARVIS_MEMORY_TOKEN"
curl http://localhost:3200/facts/some_key -H "Authorization: Bearer $JARVIS_MEMORY_TOKEN"
curl -X POST http://localhost:3200/facts -H "Authorization: Bearer $JARVIS_MEMORY_TOKEN" \
  -H "Content-Type: application/json" -d '{"key": "download_folder", "value": "D:/Jarvis/Data"}'
curl -X DELETE http://localhost:3200/facts/download_folder -H "Authorization: Bearer $JARVIS_MEMORY_TOKEN"
```

## What changed vs. the original sketch

- **Token auth on the WebSocket** (`JARVIS_MEMORY_TOKEN`, same convention
  as `browser_extension/` and `whatsapp_bridge/`). The original had a bare
  `new WebSocket.Server({ port: 8080 })` with no auth at all — on top of
  being the exact same port `browser_extension/` already uses, meaning the
  two couldn't even run simultaneously, it means any web page open in any
  browser on the machine could connect and read or overwrite every saved
  fact (download paths, preferences, anything you'd told it to remember).
- **Own ports** (8090 / 3200) so this can run alongside the other two bridges.
- **Reuses the shared `JarvisPersona`** instead of a third separate
  `speak()` implementation.
- **Input validation**: fact keys/values are trimmed and length-capped;
  `saveFact()` rejects empty key/value instead of silently storing junk.
- **Non-greedy regex** in `processInputForMemory` (`.+?` instead of `.+`
  before the ist/sind/=/als separator) so "merke dir: X ist Y als Z"
  doesn't get swallowed into the key instead of stopping at the first
  separator.
- **Error handling**: malformed WebSocket JSON and any thrown error inside
  a message handler are caught and reported back instead of crashing that
  connection.
- **A working HTTP API** — the original imported `express` and called
  `app.listen(3000)` but never registered a single route.
