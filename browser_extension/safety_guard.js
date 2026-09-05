const readline = require('readline');

/**
 * Classifies which bridge commands may run immediately and which require an
 * explicit human "yes" on the machine's own terminal — voice command alone
 * is never enough to authorize a destructive action (shell exec, file
 * writes/deletes, form submission, purchases).
 */
class SafetyGuard {
  constructor(persona) {
    this.persona = persona;
    this._approvalQueue = Promise.resolve(); // serializes concurrent prompts on one stdin

    // Patterns that mark a payload risky even for command types not
    // already hardcoded below (belt-and-braces, not the primary gate).
    this.riskyPatterns = [
      /\brm\s+-rf?\b/i, /\bdel\s+\/[sfq]/i, /\bformat\b/i,
      /\bshutdown\b/i, /\brestart\b/i, /\breg\s+add\b/i,
      /\bdrop\s+(table|database)\b/i, /\bsudo\b/i,
      /\.bat\b/i, /\.exe\b/i,
    ];

    this.riskyTypes = new Set([
      'SHELL_EXEC',
      'FILE_DELETE',
      'FILE_WRITE',
      'BROWSER_PURCHASE',
      'BROWSER_SUBMIT_FORM',
    ]);
  }

  isRisky(commandType, payload) {
    if (this.riskyTypes.has(commandType)) return true;
    const strPayload = JSON.stringify(payload || {});
    return this.riskyPatterns.some((pattern) => pattern.test(strPayload));
  }

  async requestApproval(description) {
    await this.persona.askPermission(description);

    // Chain onto the queue so two near-simultaneous risky commands don't
    // open two readline interfaces on the same stdin at once.
    const run = () => new Promise((resolve) => {
      const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
      rl.question(`[JARVIS PROMPT] "${description}" freigeben? (j/n): `, (answer) => {
        rl.close();
        const approved = ['j', 'ja', 'y', 'yes'].includes(answer.trim().toLowerCase());
        resolve(approved);
      });
    });

    const result = this._approvalQueue.then(run);
    // Keep chaining even if this prompt's caller never awaits it further.
    this._approvalQueue = result.catch(() => {});
    return result;
  }
}

module.exports = SafetyGuard;
