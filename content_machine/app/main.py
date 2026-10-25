import secrets
import threading
import traceback
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import ai, config, pipeline, store

app = FastAPI(title="Content-Maschine")
STATIC = Path(__file__).resolve().parent.parent / "static"


def auth(request: Request):
    t = request.headers.get("x-token") or request.query_params.get("t")
    if not t or not secrets.compare_digest(t, config.APP_TOKEN):
        raise HTTPException(401, "Token falsch")


@app.on_event("startup")
def _start():
    threading.Thread(target=pipeline.autopilot_loop, daemon=True).start()
    print(f"\n  Content-Maschine laeuft. App-Token: {config.APP_TOKEN}"
          f"{'  (MOCK-Modus: GEMINI_API_KEY fehlt)' if config.MOCK else ''}\n")


# -------------------------------------------------------------- Analyse
def _analyze_job(aid, paths, note):
    try:
        store.update("analyses", aid, status="running")
        store.update("analyses", aid, status="done", result=ai.analyze(paths, note))
    except Exception as e:
        traceback.print_exc()
        store.update("analyses", aid, status="failed", error=str(e)[:400])


@app.post("/api/analyze", dependencies=[Depends(auth)])
async def analyze(files: list[UploadFile] = File(...), note: str = Form("")):
    paths = []
    for f in files:
        dest = config.UPLOADS / f"{secrets.token_hex(4)}_{Path(f.filename or 'x').name}"
        with open(dest, "wb") as out:
            while chunk := await f.read(1 << 20):
                out.write(chunk)
        paths.append(dest)
    aid = store.insert("analyses", status="queued", files=[p.name for p in paths], note=note)
    threading.Thread(target=_analyze_job, args=(aid, paths, note), daemon=True).start()
    return {"id": aid}


@app.get("/api/analyses", dependencies=[Depends(auth)])
def analyses():
    return store.listing("analyses")


@app.delete("/api/analyses/{aid}", dependencies=[Depends(auth)])
def del_analysis(aid: str):
    store.delete("analyses", aid)
    return {"ok": True}


# ---------------------------------------------------------------- Posts
@app.post("/api/posts", dependencies=[Depends(auth)])
async def create_post(body: dict):
    try:
        pid = pipeline.new_post(topic=body.get("topic", ""), platforms=body.get("platforms"),
                                style=body.get("style") or pipeline.learned_style(),
                                publish_after=bool(body.get("publish")))
    except Exception as e:
        raise HTTPException(500, f"Idee fehlgeschlagen: {e}")
    return {"id": pid}


@app.get("/api/posts", dependencies=[Depends(auth)])
def posts():
    return store.listing("posts")


@app.post("/api/posts/{pid}/publish", dependencies=[Depends(auth)])
def publish_now(pid: str, body: dict | None = None):
    post = store.get("posts", pid)
    if not post or not post.get("upload_path"):
        raise HTTPException(400, "Video noch nicht fertig")
    if body and body.get("platforms"):
        store.update("posts", pid, platforms=body["platforms"])
    threading.Thread(target=pipeline.publish_post, args=(pid,), daemon=True).start()
    return {"ok": True}


@app.patch("/api/posts/{pid}", dependencies=[Depends(auth)])
def edit_post(pid: str, body: dict):
    allowed = {k: v for k, v in body.items() if k in ("caption", "hashtags", "platforms")}
    store.update("posts", pid, **allowed)
    return store.get("posts", pid)


@app.delete("/api/posts/{pid}", dependencies=[Depends(auth)])
def del_post(pid: str):
    p = store.get("posts", pid)
    for k in ("video_path", "upload_path"):
        if p and p.get(k):
            Path(p[k]).unlink(missing_ok=True)
    store.delete("posts", pid)
    return {"ok": True}


@app.get("/media/{pid}", dependencies=[Depends(auth)])
def media(pid: str, kind: str = "upload"):
    p = store.get("posts", pid)
    path = p and (p["video_path"] if kind == "master" else p["upload_path"])
    if not path or not Path(path).exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="video/mp4", filename=f"{pid}_{kind}.mp4")


@app.get("/public/{pid}/{secret}.mp4")
def public_media(pid: str, secret: str):
    """Fuer Instagram: das Video muss ueber eine oeffentliche URL abrufbar sein."""
    p = store.get("posts", pid)
    if not p or not secrets.compare_digest(secret, p.get("secret") or "x"):
        raise HTTPException(404)
    return FileResponse(p["upload_path"], media_type="video/mp4")


# ----------------------------------------------------- Einstellungen etc.
@app.get("/api/state", dependencies=[Depends(auth)])
def state():
    return {"settings": store.get_settings(), "platforms": config.platform_status(), "mock": config.MOCK,
            "resolution": config.VIDEO_RESOLUTION}


@app.put("/api/settings", dependencies=[Depends(auth)])
def settings(body: dict):
    store.set_settings(**body)
    return store.get_settings()


@app.post("/api/autopilot/run", dependencies=[Depends(auth)])
def autopilot_now():
    threading.Thread(target=pipeline.run_autopilot_once, daemon=True).start()
    return {"ok": True}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
