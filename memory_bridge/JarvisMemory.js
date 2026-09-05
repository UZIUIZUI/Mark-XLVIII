const sqlite3 = require('sqlite3');
const { open } = require('sqlite');
const path = require('path');

const MAX_KEY_LEN   = 200;
const MAX_VALUE_LEN = 2000;

class JarvisMemory {
  constructor(maxShortTermHistory = 10) {
    this.db = null;
    this.shortTermMemory = []; // in-process conversation window
    this.maxShortTermHistory = maxShortTermHistory;
  }

  async init() {
    this.db = await open({
      filename: path.join(__dirname, 'jarvis_memory.sqlite'),
      driver: sqlite3.Database,
    });

    await this.db.exec(`
      CREATE TABLE IF NOT EXISTS long_term_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT,
        fact_key TEXT UNIQUE,
        fact_value TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `);

    await this.db.exec(`
      CREATE TABLE IF NOT EXISTS conversation_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        content TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `);

    console.log('[Jarvis Memory] Database ready.');
  }

  // --- Short-term (in-process, lost on restart by design) ---
  addShortTerm(role, content) {
    this.shortTermMemory.push({ role, content, time: new Date() });
    if (this.shortTermMemory.length > this.maxShortTermHistory) {
      this.shortTermMemory.shift();
    }
  }

  getShortTermContext() {
    return this.shortTermMemory.map((m) => `${m.role.toUpperCase()}: ${m.content}`).join('\n');
  }

  // --- Long-term (SQLite, persists across restarts) ---
  async saveFact(key, value, category = 'general') {
    const cleanKey   = String(key).trim().slice(0, MAX_KEY_LEN);
    const cleanValue = String(value).trim().slice(0, MAX_VALUE_LEN);
    if (!cleanKey || !cleanValue) throw new Error('Fact key and value must be non-empty.');

    await this.db.run(
      `INSERT INTO long_term_facts (category, fact_key, fact_value)
       VALUES (?, ?, ?)
       ON CONFLICT(fact_key) DO UPDATE SET fact_value = excluded.fact_value`,
      [category, cleanKey, cleanValue]
    );

    await this.db.run(
      `INSERT INTO conversation_history (role, content) VALUES ('system_memory', ?)`,
      [`Saved: ${cleanKey} = ${cleanValue}`]
    );

    return { key: cleanKey, value: cleanValue };
  }

  async getFact(key) {
    const row = await this.db.get(`SELECT fact_value FROM long_term_facts WHERE fact_key = ?`, [key]);
    return row ? row.fact_value : null;
  }

  async deleteFact(key) {
    const result = await this.db.run(`DELETE FROM long_term_facts WHERE fact_key = ?`, [key]);
    return result.changes > 0;
  }

  async getAllFacts() {
    const rows = await this.db.all(`SELECT fact_key, fact_value FROM long_term_facts`);
    return rows.reduce((acc, row) => {
      acc[row.fact_key] = row.fact_value;
      return acc;
    }, {});
  }

  // Simple "merke dir: X ist Y" / "speichere: X ist Y" recognizer. This is
  // a best-effort convenience parser, not a real NLU step — anything more
  // ambiguous should go through an explicit saveFact() call instead.
  async processInputForMemory(userInput) {
    this.addShortTerm('user', userInput);

    const match = userInput.match(/(?:merke dir|speichere)(?:\:)?\s*(.+?)\s+(?:ist|sind|=|als)\s+(.+)/i);
    if (match) {
      const { key, value } = await this.saveFact(match[1], match[2]);
      return { saved: true, key, value };
    }
    return { saved: false };
  }
}

module.exports = JarvisMemory;
