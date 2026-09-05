const say = require('say');

class JarvisPersona {
  constructor(userName = "Sir", { voice = 'Hedda', speed = 1.0, enabled = true } = {}) {
    this.userName = userName;
    this.voice = voice; // German system voice
    this.speed = speed;
    this.enabled = enabled;
  }

  speak(text) {
    console.log(`[J.A.R.V.I.S.]: ${text}`);
    if (!this.enabled) return Promise.resolve();
    return new Promise((resolve) => {
      try {
        say.speak(text, this.voice, this.speed, (err) => {
          if (err) console.error('[Persona] TTS error:', err);
          resolve();
        });
      } catch (err) {
        console.error('[Persona] TTS unavailable:', err.message || err);
        resolve();
      }
    });
  }

  // Begrüßung (Filmgetreu, trocken, keine News)
  async greet() {
    const responses = [
      `Wie immer ein Vergnügen, ${this.userName}. Alle Systeme laufen. Ich habe mir erlaubt, die Kaffeemaschine nicht einzuschalten, da mir dazu die Hardware fehlt.`,
      `Stets zu Diensten, ${this.userName}. Ich stehe bereit... falls Sie vorhaben, heute die Gesetze der Physik zu beachten.`,
      `Systeme online. Herzlich willkommen zurück, ${this.userName}. Was planen wir heute zu zerstören?`,
    ];
    await this.speak(this.getRandom(responses));
  }

  // Bestätigung von Befehlen
  async acknowledge() {
    const responses = [
      "Sofort, Sir.",
      "Berechnungen laufen. Versuchen Sie in der Zwischenzeit ruhig, nichts anzufassen.",
      "Wird umgehend ausgeführt, Sir.",
      "Bin bereits dabei. Einen Moment bitte.",
    ];
    await this.speak(this.getRandom(responses));
  }

  // Erfolgsmeldungen
  async complete(taskName = "Vorgang") {
    const responses = [
      `Das Ziel wurde erfasst, Sir. ${taskName} ist ohne nennenswerte Explosionen abgeschlossen.`,
      `${taskName} ausgeführt. Die Daten stehen bereit, Sir.`,
      `Erfolgreich beendet. Wie erwartet fehlerfrei, Sir.`,
    ];
    await this.speak(this.getRandom(responses));
  }

  // Trockener Humor & Warnungen bei Fehleingaben oder unklaren Befehlen
  async warnOrSarcasm(scenario) {
    switch (scenario) {
      case 'no_results':
        await this.speak(`Sir, meine Berechnungen ergaben keinerlei brauchbare Ergebnisse. Vielleicht sollten wir die Suchbegriffe etwas... überdenken.`);
        break;
      case 'risky_action':
        await this.speak(`Sir, es sind noch 85 komplexe Berechnungen erforderlich, bevor ich diesen Schritt guten Gewissens empfehlen kann.`);
        break;
      case 'error':
        await this.speak(`Ein unerwarteter Fehler ist aufgetreten, Sir. Das lag mit hoher Wahrscheinlichkeit nicht an meinem Code.`);
        break;
      default:
        await this.speak(`Ich verarbeite die Anweisung, Sir... auch wenn die Sinnhaftigkeit noch geprüft wird.`);
    }
  }

  getRandom(array) {
    return array[Math.floor(Math.random() * array.length)];
  }
}

module.exports = JarvisPersona;
