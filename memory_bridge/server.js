/**
 * Jarvis Memory Bridge — a small persistent memory service for the Node
 * peripherals (browser_extension/, whatsapp_bridge/), so they can remember
 * facts ("my default download folder is D:/Jarvis/Data") across restarts.
 *
 * This is separate from the main Python app's own memory
 * (memory/memory_manager.py, memory/long_term.json) — that one backs the
 * voice assistant's conversations directly. This bridge exists so the
 * Node-side peripherals have persistent memory of their own without
 * depending on the Python process being up. If you want the two to share
 * facts, read/write memory/long_term.json from Python as usual and treat
 * this SQLite store as the Node bridges' own, separate notebook.
 *
 * Auth: exactly the same shared-secret pattern as browser_extension/ and
 * whatsapp_bridge/ — a bare, unauthenticated WebSocket on localhost can be
 * opened by any web page in any browser on the machine.
 */
const express = require('express');
const { WebSocketServer } = require('ws');
const JarvisMemory = require('./JarvisMemory');
const JarvisPersona = require('../browser_extension/persona');

const WS_PORT   = process.env.JARVIS_MEMORY_WS_PORT || 8090;
const HTTP_PORT = process.env.JARVIS_MEMORY_HTTP_PORT || 3200;
const TOKEN     = process.env.JARVIS_MEMORY_TOKEN || '';

if (!TOKEN) {
  console.error(
    '[Jarvis Memory] JARVIS_MEMORY_TOKEN is not set. Refusing to start with ' +
    'an unauthenticated memory socket — anyone able to reach it could read ' +
    'or overwrite every saved fact. Generate one with:\n' +
    '  node -e "console.log(require(\'crypto\').randomBytes(24).toString(\'hex\'))"'
  );
  process.exit(1);
}

const persona = new JarvisPersona(process.env.JARVIS_USER_NAME || 'Sir', {
  voice: process.env.JARVIS_BRIDGE_TTS_VOICE || 'Hedda',
  speed: parseFloat(process.env.JARVIS_BRIDGE_TTS_SPEED || '1.0'),
  enabled: process.env.JARVIS_BRIDGE_VOICE !== 'off',
});

const memory = new JarvisMemory();

async function startSystem() {
  await memory.init();

  const app = express();
  app.use(express.json());
  app.use((req, res, next) => {
    const auth = req.headers.authorization || '';
    if (auth !== `Bearer ${TOKEN}`) return res.status(401).json({ error: 'Unauthorized' });
    next();
  });

  app.get('/facts', async (req, res) => {
    res.json(await memory.getAllFacts());
  });

  app.get('/facts/:key', async (req, res) => {
    const value = await memory.getFact(req.params.key);
    if (value === null) return res.status(404).json({ error: 'Not found' });
    res.json({ key: req.params.key, value });
  });

  app.post('/facts', async (req, res) => {
    try {
      const { key, value, category } = req.body || {};
      if (!key || !value) return res.status(400).json({ error: 'Missing "key" or "value".' });
      const saved = await memory.saveFact(key, value, category || 'general');
      res.json({ ok: true, ...saved });
    } catch (err) {
      res.status(400).json({ ok: false, error: String(err.message || err) });
    }
  });

  app.delete('/facts/:key', async (req, res) => {
    const deleted = await memory.deleteFact(req.params.key);
    res.json({ ok: true, deleted });
  });

  app.listen(HTTP_PORT, () => {
    console.log(`[Jarvis Memory] HTTP API listening on http://localhost:${HTTP_PORT} (token required)`);
  });

  const wss = new WebSocketServer({ port: WS_PORT, verifyClient: (info, cb) => {
    try {
      const url = new URL(info.req.url, 'http://localhost');
      cb((url.searchParams.get('token') || '') === TOKEN);
    } catch {
      cb(false);
    }
  }});

  wss.on('connection', async (ws) => {
    const facts = await memory.getAllFacts();
    const factCount = Object.keys(facts).length;
    await persona.speak(`Speicher-Protokolle geladen. ${factCount} Langzeit-Einträge sind aktiv.`);

    ws.on('message', async (raw) => {
      let data;
      try {
        data = JSON.parse(raw.toString());
      } catch {
        ws.send(JSON.stringify({ ok: false, error: 'Invalid JSON.' }));
        return;
      }

      const userInput = String(data.prompt || '');
      if (!userInput) {
        ws.send(JSON.stringify({ ok: false, error: 'Missing "prompt".' }));
        return;
      }

      try {
        const memResult = await memory.processInputForMemory(userInput);
        if (memResult.saved) {
          await persona.speak(`Verstanden. Ich habe mir gemerkt, dass ${memResult.key} ${memResult.value} ist.`);
          memory.addShortTerm('jarvis', `Gemerkt: ${memResult.key} = ${memResult.value}`);
          ws.send(JSON.stringify({ ok: true, saved: true, ...memResult }));
          return;
        }

        const lower = userInput.toLowerCase();
        if (lower.includes('was weißt du über')) {
          const queryKey = userInput.replace(/was weißt du über/i, '').trim();
          const fact = await memory.getFact(queryKey);
          if (fact) {
            await persona.speak(`Laut meinen Unterlagen ist ${queryKey}: ${fact}.`);
          } else {
            await persona.warnOrSarcasm('no_results');
          }
          ws.send(JSON.stringify({ ok: true, fact: fact || null }));
          return;
        }

        await persona.acknowledge();
        memory.addShortTerm('jarvis', 'Verfahren läuft, Sir.');
        ws.send(JSON.stringify({
          ok: true,
          context: {
            longTermFacts: await memory.getAllFacts(),
            shortTermHistory: memory.getShortTermContext(),
          },
        }));
      } catch (err) {
        console.error('[Jarvis Memory] Error handling message:', err);
        await persona.warnOrSarcasm('error');
        ws.send(JSON.stringify({ ok: false, error: String(err.message || err) }));
      }
    });

    ws.on('error', (err) => console.error('[Jarvis Memory] Socket error:', err));
  });

  console.log(`[Jarvis Memory] WebSocket listening on ws://localhost:${WS_PORT} (token required)`);
}

startSystem().catch((err) => {
  console.error('[Jarvis Memory] Fatal startup error:', err);
  process.exit(1);
});
