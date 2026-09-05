// Connects to the local Jarvis Bridge (server.js) and executes DIRECT_*
// commands on the user's actual active tab via chrome.scripting —
// distinct from the separate Puppeteer window server.js also controls.

let socket = null;
let reconnectDelayMs = 1000;
const MAX_RECONNECT_DELAY_MS = 15000;

async function getConfig() {
  const { jarvisBridgePort, jarvisBridgeToken } = await chrome.storage.local.get([
    'jarvisBridgePort',
    'jarvisBridgeToken',
  ]);
  return {
    port: jarvisBridgePort || 8080,
    token: jarvisBridgeToken || '',
  };
}

async function connect() {
  const { port, token } = await getConfig();
  if (!token) {
    console.warn('[Jarvis Bridge] No token configured — open the extension popup to set one.');
    return;
  }

  socket = new WebSocket(`ws://localhost:${port}/?role=extension&token=${encodeURIComponent(token)}`);

  socket.onopen = () => {
    console.log('[Jarvis Bridge] Connected.');
    reconnectDelayMs = 1000;
  };

  socket.onmessage = async (event) => {
    let command;
    try {
      command = JSON.parse(event.data);
    } catch {
      return;
    }
    if (typeof command.action !== 'string' || !command.action.startsWith('DIRECT_')) return;

    const result = await runDirectCommand(command);
    if (command.requestId) {
      socket.send(JSON.stringify({ ...result, requestId: command.requestId }));
    }
  };

  socket.onclose = scheduleReconnect;
  socket.onerror = () => socket.close();
}

function scheduleReconnect() {
  setTimeout(connect, reconnectDelayMs);
  reconnectDelayMs = Math.min(reconnectDelayMs * 2, MAX_RECONNECT_DELAY_MS);
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || tab.id === undefined) throw new Error('No active tab.');
  if (!/^https?:\/\//i.test(tab.url || '')) {
    throw new Error('Active tab is not a regular web page.');
  }
  return tab;
}

async function runDirectCommand(command) {
  try {
    const tab = await getActiveTab();

    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['content.js'],
    });

    if (command.action === 'DIRECT_TYPE_TEXT') {
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (selector, text) => window.jarvisDriver.fill(selector, text),
        args: [String(command.selector || ''), String(command.text ?? '')],
      });
      return result;
    }

    if (command.action === 'DIRECT_CLICK') {
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (selector) => window.jarvisDriver.click(selector),
        args: [String(command.selector || '')],
      });
      return result;
    }

    return { ok: false, error: `Unknown direct action: ${command.action}` };
  } catch (err) {
    return { ok: false, error: String(err.message || err) };
  }
}

chrome.storage.onChanged.addListener((changes) => {
  if (changes.jarvisBridgeToken || changes.jarvisBridgePort) {
    if (socket) socket.close();
    connect();
  }
});

connect();
