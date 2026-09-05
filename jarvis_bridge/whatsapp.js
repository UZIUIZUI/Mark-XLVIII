const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const fs = require('fs');
const path = require('path');

const DOWNLOAD_DIR = path.join(__dirname, 'downloads');

function normalizeNumber(raw, countryCode = '49') {
  let digits = String(raw || '').replace(/[^0-9]/g, '');
  if (digits.startsWith('0')) digits = countryCode + digits.substring(1);
  return digits;
}

class JarvisWhatsApp {
  /**
   * @param {string} ownerNumber required — only this JID's messages are ever acted on.
   * @param {object} deps shared instances: { persona, onCommand }.
   *   onCommand(text) lets the unified server route recognized commands
   *   ("merke dir...", "suche ...", "öffne ...") to memory/browser in the
   *   same process — return true if it handled the message so the default
   *   'status'-only reply logic is skipped.
   */
  constructor(ownerNumber, { persona, onCommand, countryCode = '49', maxFileMB = 25 } = {}) {
    if (!ownerNumber) {
      throw new Error('ownerNumber is required — without it there is no way to tell "you" apart from any other WhatsApp contact.');
    }
    if (!persona) {
      throw new Error('JarvisWhatsApp requires a shared persona instance.');
    }
    this.countryCode = countryCode;
    this.ownerNumber = normalizeNumber(ownerNumber, countryCode);
    this.ownerJid = `${this.ownerNumber}@c.us`;
    this.persona = persona;
    this.onCommand = onCommand || (async () => false);
    this.maxFileBytes = maxFileMB * 1024 * 1024;

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

    this.client.on('auth_failure', (msg) => console.error('[Jarvis WhatsApp] Auth failure:', msg));
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

  // Only the configured owner's own chat can issue commands — anyone else
  // is logged, never acted on. A "starts with jarvis" check on any sender
  // would let any contact make the bot save files to disk and message
  // from your own account.
  async handleIncomingMessage(msg) {
    console.log(`[Jarvis WhatsApp] Message from ${msg.from}: ${msg.body?.slice(0, 80) || '(media)'}`);
    if (msg.from !== this.ownerJid) return;

    if (msg.hasMedia) {
      await this._receiveMedia(msg);
      return;
    }

    const body = msg.body || '';

    // Give the unified server first refusal — it can route "merke dir",
    // "suche", "öffne" etc. into memory/browser in the same process.
    const handled = await this.onCommand(body, msg);
    if (handled) return;

    if (body.toLowerCase().includes('status')) {
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
    if (sizeBytes > this.maxFileBytes) {
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
    const jid = `${normalizeNumber(targetNumber, this.countryCode)}@c.us`;
    await this.client.sendMessage(jid, text);
    await this.persona.speak(`Nachricht an ${targetNumber} übermittelt, ${this.persona.userName}.`);
  }

  async sendFile(targetNumber, filePath, caption = '') {
    if (!fs.existsSync(filePath)) {
      await this.persona.speak(`Sir, die angeforderte Datei unter ${filePath} konnte nicht gefunden werden.`);
      throw new Error(`File not found: ${filePath}`);
    }
    const jid = `${normalizeNumber(targetNumber, this.countryCode)}@c.us`;
    const media = MessageMedia.fromFilePath(filePath);
    await this.client.sendMessage(jid, media, { caption });
    await this.persona.speak(`Datei ${path.basename(filePath)} wurde erfolgreich versendet, ${this.persona.userName}.`);
  }
}

module.exports = { JarvisWhatsApp, normalizeNumber };
