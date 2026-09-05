/**
 * Jarvis Bridge — the ONE unified Node service combining what used to be
 * three separate bridges (browser_extension, whatsapp_bridge,
 * memory_bridge). One process, one persona, one memory, one token.
 *
 * Capabilities:
 *   - Browser automation: a dedicated Puppeteer window (SEARCH_AND_CLICK,
 *     TYPE_TEXT, GOTO, SHELL_EXEC, MOUSE_CLICK, KEYBOARD_TYPE) plus
 *     DIRECT_* commands relayed to the Chrome extension (extension/) for
 *     acting on your actual active tab.
 *   - WhatsApp: send/receive text and files, owner-JID gated. Incoming
 *     WhatsApp messages can trigger memory saves/lookups and browser
 *     commands directly — no HTTP hop, it's all one process.
 *   - Memory: SQLite-backed long-term facts + an in-process short-term
 *     window, shared by the browser and WhatsApp sides.
 *   - SafetyGuard: destructive actions (SHELL_EXEC, file writes/deletes,
 *     purchases, form submits) require an explicit "j" typed into this
 *     process's own terminal before anything runs.
 *
 * This does NOT replace the main Python app's own memory
 * (memory/memory_manager.py) or its browser automation
 * (actions/browser_control.py, Playwright) — those back the voice
 * assistant directly. This is the Node-side control surface: a Chrome
 * extension, WhatsApp, and a notebook for both.
 *
 * Config — one shared token for everything:
 *   JARVIS_TOKEN            required. Generate with:
 *     node -e "console.log(require('crypto').randomBytes(24).toString('hex'))"
 *   JARVIS_WS_PORT          default 8080  (browser bridge WebSocket)
 *   JARVIS_HTTP_PORT        default 3000  (unified HTTP API)
 *   JARVIS_USER_NAME        default "Sir"
 *   JARVIS_BRIDGE_TTS_VOICE default "Hedda"
 *   JARVIS_BRIDGE_TTS_SPEED default 1.0
 *   JARVIS_BRIDGE_VOICE     "off" disables voice feedback
 *   JARVIS_WA_OWNER_NUMBER  optional — set this to enable WhatsApp
 *   JARVIS_WA_COUNTRY_CODE  default "49"
 *   JARVIS_WA_MAX_FILE_MB   default 25
 */
const puppeteer = require('puppeteer');
const { WebSocketServer } = require('ws');
const express = require('express');
const { exec } = require('child_process');

const JarvisPersona = require('./persona');
const SafetyGuard = require('./safety_guard');
const JarvisMemory = require('./memory');
const { JarvisWhatsApp } = require('./whatsapp');

const TOKEN       = process.env.JARVIS_TOKEN || '';
const WS_PORT     = process.env.JARVIS_WS_PORT || 8080;
const HTTP_PORT   = process.env.JARVIS_HTTP_PORT || 3000;
const SHELL_EXEC_TIMEOUT_MS = 30000;

if (!TOKEN) {
  console.error(
    '[Jarvis Bridge] JARVIS_TOKEN is not set. Refusing to start with an ' +
    'unauthenticated control socket — any web page open in any browser on ' +
    'this machine could otherwise drive the browser or run shell commands. Generate one:\n' +
    '  node -e "console.log(require(\'crypto\').randomBytes(24).toString(\'hex\'))"'
  );
  process.exit(1);
}

const persona = new JarvisPersona(process.env.JARVIS_USER_NAME || 'Sir', {
  voice: process.env.JARVIS_BRIDGE_TTS_VOICE || 'Hedda',
  speed: parseFloat(process.env.JARVIS_BRIDGE_TTS_SPEED || '1.0'),
  enabled: process.env.JARVIS_BRIDGE_VOICE !== 'off',
});
const guard  = new SafetyGuard(persona);
const memory = new JarvisMemory();

let robot = null;
try {
  robot = require('robotjs');
} catch (err) {
  console.warn('[Jarvis Bridge] robotjs not available — MOUSE_CLICK/KEYBOARD_TYPE disabled:', err.message);
}

function executeShellCommand(cmd) {
  return new Promise((resolve, reject) => {
    exec(cmd, { timeout: SHELL_EXEC_TIMEOUT_MS }, (error, stdout, stderr) => {
      if (error) reject(new Error(stderr || error.message));
      else resolve(stdout);
    });
  });
}

// ── Browser bridge ───────────────────────────────────────────────────────

let browser = null;
let page = null;

async function getPage() {
  if (page && !page.isClosed()) return page;
  if (!browser || !browser.isConnected()) {
    browser = await puppeteer.launch({
      headless: false,
      defaultViewport: null,
      args: ['--start-maximized', '--disable-blink-features=AutomationControlled'],
    });
    browser.on('disconnected', () => { browser = null; page = null; });
  }
  const existing = await browser.pages();
  page = existing[0] || await browser.newPage();
  return page;
}

async function acceptCookieBanner(p) {
  try {
    const buttons = await p.$$('button');
    for (const btn of buttons) {
      const text = await p.evaluate((el) => el.textContent || '', btn);
      if (/alle akzeptieren|accept all/i.test(text)) {
        await btn.click();
        break;
      }
    }
  } catch {
    // No consent dialog, or it didn't match — proceed with the real command.
  }
}

async function handlePuppeteerCommand(action, payload) {
  const p = await getPage();

  switch (action) {
    case 'SEARCH_AND_CLICK':
    case 'BROWSER_SEARCH_AND_CLICK': {
      const query = String(payload.query || '').trim();
      if (!query) return { ok: false, error: 'Missing query.' };
      await p.goto(`https://www.google.com/search?q=${encodeURIComponent(query)}`, {
        waitUntil: 'domcontentloaded',
        timeout: 15000,
      });
      await acceptCookieBanner(p);
      try {
        await p.waitForSelector('#search h3', { timeout: 10000 });
      } catch {
        await persona.warnOrSarcasm('no_results');
        return { ok: false, error: 'No search results found.' };
      }
      await p.click('#search h3');
      await persona.complete('Die Websuche');
      return { ok: true };
    }

    case 'TYPE_TEXT': {
      const selector = String(payload.selector || '');
      const text = String(payload.text ?? '');
      if (!selector) return { ok: false, error: 'Missing selector.' };
      await p.waitForSelector(selector, { timeout: 10000 });
      await p.type(selector, text, { delay: 15 });
      await persona.complete('Die Texteingabe');
      return { ok: true };
    }

    case 'GOTO':
    case 'BROWSER_NAVIGATE': {
      const url = String(payload.url || '');
      if (!/^https?:\/\//i.test(url)) return { ok: false, error: 'Only http(s) URLs are allowed.' };
      await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
      await persona.complete('Die Navigation');
      return { ok: true };
    }

    default:
      return { ok: false, error: `Unknown action: ${action}` };
  }
}

async function handleCommand(action, payload) {
  if (action === 'MOUSE_CLICK') {
    if (!robot) return { ok: false, error: 'robotjs is not installed on this bridge.' };
    const x = Number(payload.x), y = Number(payload.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return { ok: false, error: 'Missing/invalid x, y.' };
    robot.moveMouse(x, y);
    robot.mouseClick();
    await persona.complete('Der Mausklick');
    return { ok: true };
  }

  if (action === 'KEYBOARD_TYPE') {
    if (!robot) return { ok: false, error: 'robotjs is not installed on this bridge.' };
    robot.typeString(String(payload.text ?? ''));
    await persona.complete('Die Tastatureingabe');
    return { ok: true };
  }

  if (action === 'SHELL_EXEC') {
    const cmd = String(payload.command || '').trim();
    if (!cmd) return { ok: false, error: 'Missing command.' };
    try {
      const output = await executeShellCommand(cmd);
      console.log('[Jarvis Bridge] Shell output:', output);
      await persona.complete('Der Systembefehl');
      return { ok: true, output };
    } catch (err) {
      await persona.speak('Sir, der Systembefehl wurde mit einem Fehler abgebrochen.');
      return { ok: false, error: String(err.message || err) };
    }
  }

  return handlePuppeteerCommand(action, payload);
}

// Runs a full command through the risk gate — shared by the WebSocket
// handler, the HTTP API, and WhatsApp-routed commands so all three paths
// get the exact same approval behavior.
async function runGatedCommand(action, payload, description) {
  if (guard.isRisky(action, payload)) {
    const approved = await guard.requestApproval(description || action);
    if (!approved) {
      await persona.actionDenied();
      return { ok: false, error: 'Denied by user.' };
    }
    await persona.actionApproved();
  } else {
    await persona.acknowledge();
  }
  return handleCommand(action, payload);
}

const wss = new WebSocketServer({ port: WS_PORT, verifyClient: (info, cb) => {
  try {
    const url = new URL(info.req.url, 'http://localhost');
    cb((url.searchParams.get('token') || '') === TOKEN);
  } catch {
    cb(false);
  }
}});

const extensionSockets = new Set();

wss.on('connection', (ws, req) => {
  const url = new URL(req.url, 'http://localhost');
  const role = url.searchParams.get('role') || 'client';
  if (role === 'extension') {
    extensionSockets.add(ws);
  } else {
    // Not on every extension auto-reconnect — that's the exact
    // repeated-notification annoyance the main app's own voice pipeline
    // had to be fixed for.
    persona.greet();
  }

  ws.on('close', () => extensionSockets.delete(ws));

  ws.on('message', async (raw) => {
    let command;
    try {
      command = JSON.parse(raw.toString());
    } catch {
      ws.send(JSON.stringify({ ok: false, error: 'Invalid JSON.' }));
      return;
    }

    const requestId = command.requestId;
    try {
      const action  = command.action || command.type;
      const payload = command.payload || command;
      if (typeof action !== 'string' || !action) throw new Error('Missing "action"/"type".');

      if (action.startsWith('DIRECT_')) {
        if (extensionSockets.size === 0) throw new Error('No browser extension connected.');
        for (const ext of extensionSockets) ext.send(JSON.stringify(command));
        ws.send(JSON.stringify({ ok: true, requestId, relayed: true }));
        return;
      }

      const result = await runGatedCommand(action, payload, command.description);
      ws.send(JSON.stringify({ ...result, requestId }));
    } catch (err) {
      console.error('[Jarvis Bridge] Command failed:', err);
      await persona.warnOrSarcasm('error');
      ws.send(JSON.stringify({ ok: false, requestId, error: String(err.message || err) }));
    }
  });

  ws.on('error', (err) => console.error('[Jarvis Bridge] Socket error:', err));
});

// ── WhatsApp → memory/browser routing ───────────────────────────────────
// Recognizes a small set of German command phrases in an owner message and
// handles them in-process (no HTTP hop needed — same memory, same guard,
// same browser page). Returns true if it handled the message.
async function routeWhatsAppCommand(text) {
  const memResult = await memory.processInputForMemory(text);
  if (memResult.saved) {
    await persona.speak(`Verstanden. Ich habe mir gemerkt, dass ${memResult.key} ${memResult.value} ist.`);
    memory.addShortTerm('jarvis', `Gemerkt: ${memResult.key} = ${memResult.value}`);
    return true;
  }

  const lower = text.toLowerCase();
  if (lower.includes('was weißt du über')) {
    const key = text.replace(/was weißt du über/i, '').trim();
    const fact = await memory.getFact(key);
    if (fact) await persona.speak(`Laut meinen Unterlagen ist ${key}: ${fact}.`);
    else await persona.warnOrSarcasm('no_results');
    return true;
  }

  const searchMatch = text.match(/^(?:suche|google)\s+(.+)/i);
  if (searchMatch) {
    await runGatedCommand('SEARCH_AND_CLICK', { query: searchMatch[1] }, `Websuche: ${searchMatch[1]}`);
    return true;
  }

  const gotoMatch = text.match(/^(?:öffne|navigiere zu)\s+(https?:\/\/\S+)/i);
  if (gotoMatch) {
    await runGatedCommand('GOTO', { url: gotoMatch[1] }, `Seite öffnen: ${gotoMatch[1]}`);
    return true;
  }

  return false;
}

// ── HTTP API ─────────────────────────────────────────────────────────────

function startHttpApi(whatsapp) {
  const app = express();
  app.use(express.json());
  app.use((req, res, next) => {
    if ((req.headers.authorization || '') !== `Bearer ${TOKEN}`) {
      return res.status(401).json({ error: 'Unauthorized' });
    }
    next();
  });

  app.get('/status', (req, res) => res.json({
    ok: true,
    whatsappReady: whatsapp ? whatsapp._ready : null,
    browserOpen: !!browser,
  }));

  app.post('/command', async (req, res) => {
    try {
      const { action, payload, description } = req.body || {};
      if (!action) return res.status(400).json({ error: 'Missing "action".' });
      res.json(await runGatedCommand(action, payload || {}, description));
    } catch (err) {
      res.status(500).json({ ok: false, error: String(err.message || err) });
    }
  });

  app.get('/facts', async (req, res) => res.json(await memory.getAllFacts()));
  app.get('/facts/:key', async (req, res) => {
    const value = await memory.getFact(req.params.key);
    if (value === null) return res.status(404).json({ error: 'Not found' });
    res.json({ key: req.params.key, value });
  });
  app.post('/facts', async (req, res) => {
    try {
      const { key, value, category } = req.body || {};
      if (!key || !value) return res.status(400).json({ error: 'Missing "key" or "value".' });
      res.json({ ok: true, ...(await memory.saveFact(key, value, category || 'general')) });
    } catch (err) {
      res.status(400).json({ ok: false, error: String(err.message || err) });
    }
  });
  app.delete('/facts/:key', async (req, res) => res.json({ ok: true, deleted: await memory.deleteFact(req.params.key) }));

  if (whatsapp) {
    app.post('/send-text', async (req, res) => {
      try {
        const { to, text } = req.body || {};
        if (!to || !text) return res.status(400).json({ error: 'Missing "to" or "text".' });
        await whatsapp.sendTextMessage(to, text);
        res.json({ ok: true });
      } catch (err) {
        res.status(500).json({ ok: false, error: String(err.message || err) });
      }
    });

    app.post('/send-file', async (req, res) => {
      try {
        const { to, filePath, caption } = req.body || {};
        if (!to || !filePath) return res.status(400).json({ error: 'Missing "to" or "filePath".' });
        await whatsapp.sendFile(to, filePath, caption || '');
        res.json({ ok: true });
      } catch (err) {
        res.status(500).json({ ok: false, error: String(err.message || err) });
      }
    });
  }

  app.listen(HTTP_PORT, () => {
    console.log(`[Jarvis Bridge] HTTP API listening on http://localhost:${HTTP_PORT} (token required)`);
  });
}

// ── Startup ──────────────────────────────────────────────────────────────

async function main() {
  await memory.init();

  let whatsapp = null;
  const ownerNumber = process.env.JARVIS_WA_OWNER_NUMBER || '';
  if (ownerNumber) {
    whatsapp = new JarvisWhatsApp(ownerNumber, {
      persona,
      countryCode: process.env.JARVIS_WA_COUNTRY_CODE || '49',
      maxFileMB: parseFloat(process.env.JARVIS_WA_MAX_FILE_MB || '25'),
      onCommand: routeWhatsAppCommand,
    });
  } else {
    console.log('[Jarvis Bridge] JARVIS_WA_OWNER_NUMBER not set — WhatsApp disabled (browser bridge + memory still run).');
  }

  startHttpApi(whatsapp);
  console.log(`[Jarvis Bridge] Browser WebSocket listening on ws://localhost:${WS_PORT} (token required)`);
}

main().catch((err) => {
  console.error('[Jarvis Bridge] Fatal startup error:', err);
  process.exit(1);
});

process.on('SIGINT', async () => {
  console.log('\n[Jarvis Bridge] Shutting down...');
  if (browser) await browser.close().catch(() => {});
  process.exit(0);
});
