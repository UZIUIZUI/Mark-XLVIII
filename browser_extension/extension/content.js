// Injected on demand by background.js via chrome.scripting.executeScript —
// runs in the page's DOM, automates the *user's actual active tab*
// (distinct from the separate Puppeteer-controlled window run by server.js).

window.jarvisDriver = {
  click(selector) {
    const el = document.querySelector(selector);
    if (!el) return { ok: false, error: `No element matches: ${selector}` };
    el.click();
    return { ok: true };
  },

  fill(selector, text) {
    const el = document.querySelector(selector);
    if (!el) return { ok: false, error: `No element matches: ${selector}` };
    el.focus();
    el.value = text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return { ok: true };
  },
};
