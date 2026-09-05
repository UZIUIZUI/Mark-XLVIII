/**
 * Jarvis Browser Bridge — local Node server.
 *
 * Runs a dedicated, Puppeteer-controlled Chrome window for command-driven
 * browsing (SEARCH_AND_CLICK, TYPE_TEXT, ...), and relays DIRECT_* commands
 * to the Jarvis Browser Extension so it can act on the user's *actual*
 * active Chrome tab via chrome.scripting instead.
 *
 * Auth: every WebSocket connection (extension or any other client) must
 * present the shared secret configured in JARVIS_BRIDGE_TOKEN as a query
 * param, e.g. ws://localhost:8080?token=<token>. Without this, any web
 * page open in any browser on the machine could open a plain
 * `new WebSocket('ws://localhost:8080')` and drive the browser — the
 * classic unauthenticated-localhost-service drive-by. Generate one with:
 *   node -e "console.log(require('crypto').randomBytes(24).toString('hex'))"
 */
const puppeteer = require('puppeteer');
const { WebSocketServer } = require('ws');
const JarvisPersona = require('./persona');

const PORT  = process.env.JARVIS_BRIDGE_PORT || 8080;
const TOKEN = process.env.JARVIS_BRIDGE_TOKEN || '';
const VOICE_ENABLED = process.env.JARVIS_BRIDGE_VOICE !== 'off';

const persona = new JarvisPersona(process.env.JARVIS_USER_NAME || 'Sir', {
  voice: process.env.JARVIS_BRIDGE_TTS_VOICE || 'Hedda',
  speed: parseFloat(process.env.JARVIS_BRIDGE_TTS_SPEED || '1.0'),
  enabled: VOICE_ENABLED,
});

if (!TOKEN) {
  console.error(
    '[Jarvis Bridge] JARVIS_BRIDGE_TOKEN is not set. Refusing to start with ' +
    'an unauthenticated control socket. Set it, e.g.:\n' +
    '  JARVIS_BRIDGE_TOKEN=$(node -e "console.log(require(\'crypto\').randomBytes(24).toString(\'hex\'))") node server.js'
  );
  process.exit(1);
}

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
  // Best-effort — most consent dialogs are gone by the time this runs, and
  // that's fine; this never blocks the actual command on failure.
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

async function handlePuppeteerCommand(command) {
  const p = await getPage();

  switch (command.action) {
    case 'SEARCH_AND_CLICK': {
      const query = String(command.query || '').trim();
      if (!query) return { ok: false, error: 'Missing query.' };
      await persona.acknowledge();
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
      const selector = String(command.selector || '');
      const text = String(command.text ?? '');
      if (!selector) return { ok: false, error: 'Missing selector.' };
      await p.waitForSelector(selector, { timeout: 10000 });
      await p.type(selector, text, { delay: 15 });
      await persona.complete('Die Texteingabe');
      return { ok: true };
    }

    case 'GOTO': {
      const url = String(command.url || '');
      if (!/^https?:\/\//i.test(url)) {
        return { ok: false, error: 'Only http(s) URLs are allowed.' };
      }
      await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
      return { ok: true };
    }

    default:
      return { ok: false, error: `Unknown Puppeteer action: ${command.action}` };
  }
}

const wss = new WebSocketServer({ port: PORT, verifyClient: (info, cb) => {
  try {
    const url = new URL(info.req.url, 'http://localhost');
    const supplied = url.searchParams.get('token') || '';
    cb(supplied === TOKEN);
  } catch {
    cb(false);
  }
}});

// Extension connections are tracked separately so Puppeteer-side clients
// (e.g. a CLI test script) can also connect without being confused for it.
const extensionSockets = new Set();

wss.on('connection', (ws, req) => {
  const url = new URL(req.url, 'http://localhost');
  const role = url.searchParams.get('role') || 'client';
  if (role === 'extension') {
    extensionSockets.add(ws);
  } else {
    // Greet on command-client connections only — the extension reconnects
    // automatically with backoff, and re-greeting on every reconnect would
    // be the exact repeated-notification annoyance Jarvis's voice pipeline
    // already had to be fixed for.
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
      if (typeof command.action !== 'string') {
        throw new Error('Missing "action".');
      }

      if (command.action.startsWith('DIRECT_')) {
        // Relay to the extension so it acts on the user's real active tab.
        if (extensionSockets.size === 0) {
          throw new Error('No browser extension connected.');
        }
        for (const ext of extensionSockets) {
          ext.send(JSON.stringify(command));
        }
        ws.send(JSON.stringify({ ok: true, requestId, relayed: true }));
        return;
      }

      const result = await handlePuppeteerCommand(command);
      ws.send(JSON.stringify({ ...result, requestId }));
    } catch (err) {
      console.error('[Jarvis Bridge] Command failed:', err);
      await persona.warnOrSarcasm('error');
      ws.send(JSON.stringify({ ok: false, requestId, error: String(err.message || err) }));
    }
  });

  ws.on('error', (err) => console.error('[Jarvis Bridge] Socket error:', err));
});

console.log(`[Jarvis Bridge] Listening on ws://localhost:${PORT} (token required)`);

process.on('SIGINT', async () => {
  console.log('\n[Jarvis Bridge] Shutting down...');
  if (browser) await browser.close().catch(() => {});
  process.exit(0);
});
