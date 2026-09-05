/**
 * Jarvis WhatsApp Bridge — whatsapp-web.js client + a small local HTTP API
 * so the Python Jarvis app can send WhatsApp text/files programmatically
 * (a more reliable alternative to actions/send_message.py's WhatsApp
 * Desktop UI-automation path, which types into the app via pyautogui).
 *
 * Config comes from environment variables, not hardcoded values:
 *   JARVIS_WA_OWNER_NUMBER   — required. Your own number, digits only or
 *                              with leading 0/+, e.g. "015568810689".
 *   JARVIS_WA_COUNTRY_CODE   — default "49" (Germany). Used only when a
 *                              number starts with a leading 0.
 *   JARVIS_WA_HTTP_TOKEN     — required to enable the HTTP API. Same
 *                              shared-secret pattern as browser_extension/.
 *   JARVIS_WA_HTTP_PORT      — default 3100.
 *   JARVIS_WA_MAX_FILE_MB    — default 25. Incoming media larger than this
 *                              is rejected instead of written to disk.
 *   JARVIS_BRIDGE_VOICE      — "off" disables voice feedback (shared
 *                              convention with browser_extension/).
 */
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const fs = require('fs');
const path = require('path');

const JarvisPersona = require('../browser_extension/persona');

const DOWNLOAD_DIR   = path.join(__dirname, 'downloads');
const MAX_FILE_BYTES = (parseFloat(process.env.JARVIS_WA_MAX_FILE_MB || '25')) * 1024 * 1024;
const COUNTRY_CODE   = process.env.JARVIS_WA_COUNTRY_CODE || '49';

function normalizeNumber(raw) {
  let digits = String(raw || '').replace(/[^0-9]/g, '');
  if (digits.startsWith('0')) digits = COUNTRY_CODE + digits.substring(1);
  return digits;
}

class JarvisWhatsApp {
  constructor(ownerNumber) {
    if (!ownerNumber) {
      throw new Error(
        'JARVIS_WA_OWNER_NUMBER is not set. Refusing to start — without a fixed ' +
        'owner number, any WhatsApp contact could be treated as "you".'
      );
    }
    this.ownerNumber = normalizeNumber(ownerNumber);
    this.ownerJid = `${this.ownerNumber}@c.us`;

    this.persona = new JarvisPersona(process.env.JARVIS_USER_NAME || 'Sir', {
      voice: process.env.JARVIS_BRIDGE_TTS_VOICE || 'Hedda',
      speed: parseFloat(process.env.JARVIS_BRIDGE_TTS_SPEED || '1.0'),
      enabled: process.env.JARVIS_BRIDGE_VOICE !== 'off',
    });

    if (!fs.existsSync(DOWNLOAD_DIR)) fs.mkdirSync(DOWNLOAD_DIR, { recursive: true });

    this.client = new Client({
      authStrategy: new LocalAuth({ clientId: 'jarvis-whatsapp' }),
      puppeteer: {
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
      },
    });

    this._ready = false;
    this.initEvents();
  }

  initEvents() {
    this.client.on('qr', (qr) => {
      console.log('[Jarvis WhatsApp] Scan this QR code with WhatsApp (Linked devices):');
      qrcode.generate(qr, { small: true });
    });

    this.client.on('ready', async () => {
      this._ready = true;
      console.log(`[Jarvis WhatsApp] Connected as owner number ${this.ownerNumber}.`);
      await this.persona.speak(`WhatsApp-Schnittstelle erfolgreich gekoppelt, ${this.persona.userName}.`);
    });

    this.client.on('auth_failure', (msg) => {
      console.error('[Jarvis WhatsApp] Auth failure:', msg);
    });

    this.client.on('disconnected', (reason) => {
      this._ready = false;
      console.warn('[Jarvis WhatsApp] Disconnected:', reason);
    });

    this.client.on('message', async (msg) => {
      try {
        await this.handleIncomingMessage(msg);
      } catch (err) {
        console.error('[Jarvis WhatsApp] Error handling message:', err);
      }
    });

    this.client.on('incoming_call', async (call) => {
      try {
        await this.persona.speak(`Ein eingehender WhatsApp-Anruf von ${call.from}.`);
        await this.client.sendMessage(this.ownerJid, `[J.A.R.V.I.S.] Eingehender Anruf erkannt von: ${call.from}`);
      } catch (err) {
        console.error('[Jarvis WhatsApp] Error handling call event:', err);
      }
    });

    this.client.initialize();
  }

  // Only the configured owner's own chat is ever treated as a command
  // source. A message from anyone else starting with "jarvis" used to be
  // enough in the original draft — that would let any WhatsApp contact
  // make the bot save files to your disk and send messages from your
  // account. Non-owner messages are only logged, never acted on.
  async handleIncomingMessage(msg) {
    console.log(`[Jarvis WhatsApp] Message from ${msg.from}: ${msg.body?.slice(0, 80) || '(media)'}`);

    if (msg.from !== this.ownerJid) return;

    if (msg.hasMedia) {
      await this._receiveMedia(msg);
      return;
    }

    const body = (msg.body || '').toLowerCase();
    if (body.includes('status')) {
      await msg.reply('[J.A.R.V.I.S.] Alle Systeme laufen nominal, Sir.');
    }
  }

  async _receiveMedia(msg) {
    let media;
    try {
      media = await msg.downloadMedia();
    } catch (err) {
      console.error('[Jarvis WhatsApp] downloadMedia failed:', err);
      await msg.reply('[J.A.R.V.I.S.] Datei konnte nicht heruntergeladen werden, Sir.');
      return;
    }
    if (!media || !media.data) return;

    const sizeBytes = Buffer.byteLength(media.data, 'base64');
    if (sizeBytes > MAX_FILE_BYTES) {
      await this.persona.speak('Sir, die eingehende Datei überschreitet das erlaubte Größenlimit und wurde verworfen.');
      await msg.reply('[J.A.R.V.I.S.] Datei zu groß, wurde nicht gespeichert.');
      return;
    }

    let ext = 'bin';
    try {
      ext = (media.mimetype.split('/')[1] || 'bin').split(';')[0].replace(/[^a-z0-9]/gi, '') || 'bin';
    } catch {
      // keep default extension
    }
    const filename = `received_${Date.now()}.${ext}`;
    const filePath = path.join(DOWNLOAD_DIR, filename);

    try {
      fs.writeFileSync(filePath, media.data, { encoding: 'base64' });
    } catch (err) {
      console.error('[Jarvis WhatsApp] Failed to save media:', err);
      await msg.reply('[J.A.R.V.I.S.] Datei konnte nicht gespeichert werden, Sir.');
      return;
    }

    await this.persona.speak(`Eine neue Datei wurde empfangen und gespeichert unter ${filename}.`);
    await msg.reply('[J.A.R.V.I.S.] Datei empfangen und gesichert, Sir.');
  }

  async sendTextMessage(targetNumber, text) {
    const jid = `${normalizeNumber(targetNumber)}@c.us`;
    await this.client.sendMessage(jid, text);
    await this.persona.speak(`Nachricht an ${targetNumber} übermittelt, ${this.persona.userName}.`);
  }

  async sendFile(targetNumber, filePath, caption = '') {
    if (!fs.existsSync(filePath)) {
      await this.persona.speak(`Sir, die angeforderte Datei unter ${filePath} konnte nicht gefunden werden.`);
      throw new Error(`File not found: ${filePath}`);
    }
    const jid = `${normalizeNumber(targetNumber)}@c.us`;
    const media = MessageMedia.fromFilePath(filePath);
    await this.client.sendMessage(jid, media, { caption });
    await this.persona.speak(`Datei ${path.basename(filePath)} wurde erfolgreich versendet, ${this.persona.userName}.`);
  }
}

function startHttpApi(jarvisWA) {
  const token = process.env.JARVIS_WA_HTTP_TOKEN || '';
  const port  = process.env.JARVIS_WA_HTTP_PORT || 3100;

  if (!token) {
    console.warn('[Jarvis WhatsApp] JARVIS_WA_HTTP_TOKEN not set — HTTP API disabled (WhatsApp client still runs).');
    return;
  }

  const app = express();
  app.use(express.json());

  app.use((req, res, next) => {
    const auth = req.headers.authorization || '';
    if (auth !== `Bearer ${token}`) return res.status(401).json({ error: 'Unauthorized' });
    next();
  });

  app.post('/send-text', async (req, res) => {
    try {
      const { to, text } = req.body || {};
      if (!to || !text) return res.status(400).json({ error: 'Missing "to" or "text".' });
      await jarvisWA.sendTextMessage(to, text);
      res.json({ ok: true });
    } catch (err) {
      res.status(500).json({ ok: false, error: String(err.message || err) });
    }
  });

  app.post('/send-file', async (req, res) => {
    try {
      const { to, filePath, caption } = req.body || {};
      if (!to || !filePath) return res.status(400).json({ error: 'Missing "to" or "filePath".' });
      await jarvisWA.sendFile(to, filePath, caption || '');
      res.json({ ok: true });
    } catch (err) {
      res.status(500).json({ ok: false, error: String(err.message || err) });
    }
  });

  app.get('/status', (req, res) => res.json({ ready: jarvisWA._ready }));

  app.listen(port, () => console.log(`[Jarvis WhatsApp] HTTP API listening on http://localhost:${port} (token required)`));
}

if (require.main === module) {
  const jarvisWA = new JarvisWhatsApp(process.env.JARVIS_WA_OWNER_NUMBER);
  startHttpApi(jarvisWA);
}

module.exports = { JarvisWhatsApp, normalizeNumber, startHttpApi };
