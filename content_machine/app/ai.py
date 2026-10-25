"""Gemini: Medien analysieren, Ideen/Skripte schreiben, Veo-Videos erzeugen."""
import json
import shutil
import subprocess
import time
from pathlib import Path

from . import config

_client = None


def client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    return json.loads(text)


# ---------------------------------------------------------------- Analyse
ANALYZE_PROMPT = """Du bist Senior-Stratege fuer TikTok und Instagram Reels.
Analysiere das Material (Bilder/Videos) und antworte NUR als JSON:
{
 "summary": "Was ist zu sehen, 2 Saetze",
 "score": 0-100 (Viral-Potenzial),
 "hook": "Bewertung der ersten 2 Sekunden / des Aufmerksamkeitsankers",
 "strengths": ["..."],
 "weaknesses": ["..."],
 "style_prompt": "Wiederverwendbare Stil-Beschreibung (Licht, Farben, Kamera, Tempo, Stimmung) fuer KI-Videogenerierung, englisch",
 "ideas": [{"topic": "...", "hook": "..."}],
 "hashtags": ["..."]
}
Schreibe auf Deutsch (style_prompt englisch). Gib 3 ideas."""


def analyze(paths, note=""):
    if config.MOCK:
        return {"summary": "MOCK: Kein GEMINI_API_KEY gesetzt.", "score": 50, "hook": "-",
                "strengths": ["Demo"], "weaknesses": ["Demo"],
                "style_prompt": "cinematic, warm light, handheld, shallow depth of field",
                "ideas": [{"topic": "Demo-Idee", "hook": "Das hast du noch nie gesehen"}],
                "hashtags": ["#demo"]}
    from google.genai import types
    parts = []
    for p in paths:
        f = client().files.upload(file=str(p))
        while getattr(f.state, "name", "") == "PROCESSING":  # Videos brauchen Verarbeitung
            time.sleep(3)
            f = client().files.get(name=f.name)
        parts.append(f)
    parts.append(ANALYZE_PROMPT + (f"\nZusatzinfo vom Nutzer: {note}" if note else ""))
    r = client().models.generate_content(
        model=config.TEXT_MODEL, contents=parts,
        config=types.GenerateContentConfig(response_mime_type="application/json"))
    return _json(r.text)


# ------------------------------------------------------------------ Ideen
IDEA_PROMPT = """Du bist Content-Produzent fuer TikTok und Instagram Reels (Hochformat 9:16, 8 Sekunden Clip mit Ton).
Nische: {niche}
Thema-Wunsch: {topic}
Gelernte Stilvorgaben aus der Analyse des Nutzers: {style}
Bereits produzierte Themen (nicht wiederholen): {done}

Antworte NUR als JSON:
{{"topic": "...", "hook": "erster Satz / Aufhaenger", 
 "video_prompt": "Detaillierter englischer Veo-Prompt: Szene, Kamera, Licht, Bewegung, Ton/Dialog, 9:16, cinematic 4K",
 "caption": "Caption auf Deutsch, Hook in Zeile 1, kurzer CTA",
 "hashtags": ["#..", "#..", "#..", "#..", "#.."]}}"""


def make_idea(niche, topic="", style="", done=()):
    if config.MOCK:
        return {"topic": topic or "Demo-Video", "hook": "Wusstest du das?",
                "video_prompt": "cinematic test pattern", "caption": "Demo-Caption\n\nMOCK-Modus",
                "hashtags": ["#demo", "#test"]}
    from google.genai import types
    r = client().models.generate_content(
        model=config.TEXT_MODEL,
        contents=IDEA_PROMPT.format(niche=niche or "frei waehlbar", topic=topic or "waehle selbst ein starkes Thema",
                                    style=style or "keine", done=", ".join(done) or "keine"),
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=1.0))
    return _json(r.text)


# ------------------------------------------------------------------ Video
def _ffprobe_height(path):
    if not shutil.which("ffprobe"):
        return 0
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=height", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return int(out.stdout.strip())
    except ValueError:
        return 0


def _upscale_4k(src, dst):
    subprocess.run(["ffmpeg", "-y", "-i", str(src), "-vf",
                    "scale=2160:3840:flags=lanczos:force_original_aspect_ratio=increase,crop=2160:3840",
                    "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-c:a", "copy", str(dst)],
                   check=True, capture_output=True)


def render_video(prompt, out: Path):
    """Erzeugt ein 9:16-Video. Gibt (pfad, native_hoehe) zurueck."""
    if config.MOCK:
        if not shutil.which("ffmpeg"):
            raise RuntimeError("Mock-Modus braucht ffmpeg")
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=3:r=30",
                        "-pix_fmt", "yuv420p", str(out)], check=True, capture_output=True)
        return out, 1920
    from google.genai import types
    want = config.VIDEO_RESOLUTION
    chain = [want] + [r for r in ("1080p", "720p") if r != want]
    op, last_err = None, None
    for res in chain:
        try:
            op = client().models.generate_videos(
                model=config.VIDEO_MODEL, prompt=prompt,
                config=types.GenerateVideosConfig(aspect_ratio="9:16", resolution=res))
            break
        except Exception as e:  # Modell/Aufloesung nicht verfuegbar -> naechste Stufe
            last_err = e
    if op is None:
        raise RuntimeError(f"Veo-Start fehlgeschlagen: {last_err}")
    while not op.done:
        time.sleep(10)
        op = client().operations.get(op)
    vids = getattr(op.response, "generated_videos", None)
    if not vids:
        raise RuntimeError("Veo hat kein Video geliefert (evtl. Inhalts-Filter). Prompt aendern.")
    client().files.download(file=vids[0].video)
    vids[0].video.save(str(out))
    return out, _ffprobe_height(out)


def finalize(master: Path):
    """Stellt 4K-Master sicher + erzeugt 1080p-Upload-Kopie. Gibt (master, upload, note) zurueck."""
    note = ""
    h = _ffprobe_height(master)
    if shutil.which("ffmpeg"):
        if config.VIDEO_RESOLUTION == "4k" and 0 < h < 3840:
            up = master.with_name(master.stem + "_4k.mp4")
            _upscale_4k(master, up)
            note = f"Modell lieferte {h}p, per Lanczos auf 4K hochskaliert (kein natives 4K)."
            master = up
        upload = master.with_name(master.stem + "_upload.mp4")
        subprocess.run(["ffmpeg", "-y", "-i", str(master), "-vf", "scale=1080:1920:flags=lanczos",
                        "-c:v", "libx264", "-crf", "20", "-preset", "fast", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-movflags", "+faststart", str(upload)],
                       check=True, capture_output=True)
    else:
        upload = master
        note = "ffmpeg fehlt: kein Upscale/Upload-Transcode."
    return master, upload, note
