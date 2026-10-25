# ⚡ Content-Maschine (TikTok + Instagram, fürs Handy)

Handy-App (PWA) + Server. Zwei Modi:

1. **Manuell:** Bilder/Videos hochladen → KI analysiert (Hook, Stärken, Schwächen, Viral-Score, Ideen) und merkt sich den Stil.
2. **Autopilot:** Die Maschine erfindet selbst Themen, schreibt Skript + Caption + Hashtags, erzeugt ein 9:16-KI-Video mit Ton (Veo) in 4K und postet es – oder legt es zur Freigabe in die Warteschlange.

## 📱 Handy-App ohne Server (`standalone/`)

Läuft komplett im Handy: Analyse und Veo-Videos direkt über deinen Gemini-Key, Daten und Videos bleiben auf dem Handy (IndexedDB). Kein PC nötig.

- Veröffentlichung per Workflow `.github/workflows/pages.yml` (GitHub Pages): Adresse danach `https://<user>.github.io/<repo>/`. Im Handy-Browser öffnen → „Zum Home-Bildschirm“ (Android: „App installieren“).
- Unter **Autopilot** den Gemini-Key eintragen.
- **Posten** = Teilen-Menü → TikTok / Instagram wählen (Caption wird automatisch kopiert). Direkt-Upload per API gibt es nur in der Server-Version.
- **Autopilot** läuft nur, solange die App geöffnet ist (Handy-Browser kann im Hintergrund nichts ausführen). Für echten 24/7-Betrieb die Server-Version nutzen.
- Der Key liegt im Handy-Speicher; nutze einen eigenen Key mit Budget-Limit.

---

## Start (Server-Version, Vollautomatik + API-Upload)

```bash
cd content_machine
cp .env.example .env     # GEMINI_API_KEY eintragen
./run.sh                 # Token steht im Log / data/token.txt
```

Ohne `GEMINI_API_KEY` läuft ein **Demo-Modus** (Testvideo), nichts wird gepostet.

### Aufs Handy
- Gleiches WLAN: `http://<PC-IP>:8000` im Handy-Browser öffnen → „Zum Home-Bildschirm“.
- Von überall: Server auf einen VPS/Raspberry Pi mit `https` (z. B. Cloudflare Tunnel oder Tailscale Funnel). **Instagram braucht zwingend eine öffentliche https-URL** (`PUBLIC_BASE_URL`), weil Meta das Video selbst abruft.
- Zugriff ist durch den App-Token geschützt – gib den Server nie ohne ihn frei.

## Ehrliche Grenzen

| Thema | Realität |
|---|---|
| **4K** | Es wird 4K bei Veo angefragt; liefert das Modell weniger, fallback auf 1080p/720p und ffmpeg-Upscale auf 2160×3840 (steht dann im Post vermerkt, ist **kein natives 4K**). Hochgeladen wird eine 1080×1920-Kopie (IG/TikTok skalieren ohnehin runter, kleinere Datei); der 4K-Master ist per ⬇️ ladbar. |
| **Kosten** | Veo rechnet pro Sekunde ab. Autopilot mit hoher Frequenz kann teuer werden – Standard ist 1 Video / 12 h und manuelle Freigabe. |
| **Instagram** | Instagram-Business/Creator-Konto + Meta-App + langlebiger Token (`IG_USER_ID`, `IG_ACCESS_TOKEN`). |
| **TikTok** | Content-Posting-API-Zugang nötig. Solange deine TikTok-App nicht auditiert ist, sind API-Posts nur **privat (SELF_ONLY)** sichtbar. Alternative: 📲 *Teilen* öffnet das Handy-Teilen-Menü direkt zur TikTok-/Instagram-App. |
| **KI-Kennzeichnung** | TikTok/Instagram verlangen, KI-generierte Inhalte zu kennzeichnen – ergänze das in der Caption/den App-Einstellungen. |
| **Inhaltsfilter** | Veo lehnt manche Prompts ab; der Post steht dann auf „Fehler“ und kann gelöscht/neu erzeugt werden. |

## Aufbau
`app/ai.py` Gemini + Veo · `app/publish.py` IG/TikTok · `app/pipeline.py` Idee→Video→Post + Autopilot-Loop · `app/main.py` API · `static/` Handy-UI.
