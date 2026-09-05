const portInput   = document.getElementById('port');
const tokenInput  = document.getElementById('token');
const statusEl    = document.getElementById('status');

chrome.storage.local.get(['jarvisBridgePort', 'jarvisBridgeToken'], (cfg) => {
  portInput.value  = cfg.jarvisBridgePort || 8080;
  tokenInput.value = cfg.jarvisBridgeToken || '';
  statusEl.textContent = cfg.jarvisBridgeToken ? 'Configured.' : 'Not configured yet.';
});

document.getElementById('save').addEventListener('click', async () => {
  const port  = parseInt(portInput.value, 10) || 8080;
  const token = tokenInput.value.trim();
  if (!token) {
    statusEl.textContent = 'Token is required.';
    return;
  }
  await chrome.storage.local.set({ jarvisBridgePort: port, jarvisBridgeToken: token });
  statusEl.textContent = 'Saved — reconnecting...';
});
