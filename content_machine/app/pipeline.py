"""Ablauf: Idee -> Video -> (optional) Veroeffentlichen. Plus Autopilot-Schleife."""
import secrets
import threading
import time
import traceback

from . import ai, config, publish, store


def produce(post_id, publish_after=False):
    """Laeuft im Thread: erzeugt das Video fuer einen vorbereiteten Post."""
    try:
        post = store.get("posts", post_id)
        store.update("posts", post_id, status="generating")
        out = config.VIDEOS / f"{post_id}.mp4"
        raw, _ = ai.render_video(post["video_prompt"], out)
        master, upload, note = ai.finalize(raw)
        store.update("posts", post_id, status="ready", video_path=str(master), upload_path=str(upload),
                     error=note or None)
        if publish_after:
            publish_post(post_id)
    except Exception as e:
        traceback.print_exc()
        store.update("posts", post_id, status="failed", error=str(e)[:400])


def publish_post(post_id):
    post = store.get("posts", post_id)
    store.update("posts", post_id, status="publishing")
    results = publish.publish(post, post["platforms"])
    ok = [p for p, r in results.items() if r.get("ok")]
    store.update("posts", post_id, results=results,
                 status="published" if ok else "ready")


def new_post(topic="", platforms=None, style="", source="manual", publish_after=False):
    s = store.get_settings()
    done = [p["topic"] for p in store.listing("posts", 15) if p.get("topic")]
    idea = ai.make_idea(s["niche"], topic, style, done)
    pid = store.insert("posts", status="queued", source=source, topic=idea["topic"], hook=idea.get("hook"),
                       video_prompt=idea["video_prompt"], caption=idea["caption"],
                       hashtags=idea.get("hashtags", []), platforms=platforms or s["platforms"],
                       secret=secrets.token_urlsafe(16), results={})
    threading.Thread(target=produce, args=(pid, publish_after), daemon=True).start()
    return pid


def learned_style():
    """Fasst die Stil-Vorgaben der letzten Analysen fuer den Autopiloten zusammen."""
    ok = [a for a in store.listing("analyses", 5) if a["status"] == "done" and a.get("result")]
    return " | ".join(a["result"].get("style_prompt", "") for a in ok if a["result"].get("style_prompt"))


def run_autopilot_once():
    s = store.get_settings()
    store.set_settings(last_run=time.time())
    for _ in range(int(s["videos_per_run"])):
        try:
            new_post(style=learned_style(), source="autopilot", publish_after=bool(s["auto_publish"]))
        except Exception:
            traceback.print_exc()


def autopilot_loop():
    while True:
        try:
            s = store.get_settings()
            if s["autopilot"] and time.time() - s["last_run"] >= s["interval_hours"] * 3600:
                run_autopilot_once()
        except Exception:
            traceback.print_exc()
        time.sleep(60)
