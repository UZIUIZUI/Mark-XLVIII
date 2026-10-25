"""Upload zu Instagram (Reels, Graph API) und TikTok (Content Posting API)."""
import os
import time

import requests

from . import config

GRAPH = "https://graph.facebook.com/v21.0"


def full_caption(post):
    tags = " ".join(post.get("hashtags") or [])
    return f"{post.get('caption', '')}\n\n{tags}".strip()


def instagram(post):
    if not platform_ok("instagram"):
        raise RuntimeError("Instagram nicht konfiguriert (IG_USER_ID, IG_ACCESS_TOKEN, PUBLIC_BASE_URL)")
    url = f"{config.PUBLIC_BASE_URL}/public/{post['id']}/{post['secret']}.mp4"
    r = requests.post(f"{GRAPH}/{config.IG_USER_ID}/media", data={
        "media_type": "REELS", "video_url": url, "caption": full_caption(post),
        "access_token": config.IG_ACCESS_TOKEN}, timeout=60)
    r.raise_for_status()
    cid = r.json()["id"]
    for _ in range(60):  # bis ~10 Min. auf Verarbeitung warten
        s = requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code,status",
                         "access_token": config.IG_ACCESS_TOKEN}, timeout=30).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram-Verarbeitung: {s.get('status')}")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram-Verarbeitung Timeout")
    p = requests.post(f"{GRAPH}/{config.IG_USER_ID}/media_publish", data={
        "creation_id": cid, "access_token": config.IG_ACCESS_TOKEN}, timeout=60)
    p.raise_for_status()
    return {"ok": True, "id": p.json().get("id")}


def tiktok(post):
    if not platform_ok("tiktok"):
        raise RuntimeError("TikTok nicht konfiguriert (TIKTOK_ACCESS_TOKEN)")
    path = post["upload_path"]
    size = os.path.getsize(path)
    chunk = 10 * 1024 * 1024 if size > 10 * 1024 * 1024 else size
    total = max(1, size // chunk)  # letzter Chunk nimmt den Rest auf
    h = {"Authorization": f"Bearer {config.TIKTOK_ACCESS_TOKEN}", "Content-Type": "application/json; charset=UTF-8"}
    init = requests.post("https://open.tiktokapis.com/v2/post/publish/video/init/", headers=h, json={
        "post_info": {"title": full_caption(post)[:2200], "privacy_level": config.TIKTOK_PRIVACY,
                      "disable_comment": False},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk,
                        "total_chunk_count": total}}, timeout=60)
    init.raise_for_status()
    body = init.json()
    if body.get("error", {}).get("code", "ok") != "ok":
        raise RuntimeError(f"TikTok: {body['error']}")
    up, pid = body["data"]["upload_url"], body["data"]["publish_id"]
    with open(path, "rb") as f:
        for i in range(total):
            start = i * chunk
            data = f.read(chunk if i < total - 1 else size - start)
            r = requests.put(up, data=data, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(data)),
                "Content-Range": f"bytes {start}-{start + len(data) - 1}/{size}"}, timeout=600)
            r.raise_for_status()
    return {"ok": True, "id": pid, "note": f"Privatsphaere: {config.TIKTOK_PRIVACY}"}


def platform_ok(name):
    return config.platform_status()[name]


def publish(post, platforms):
    results = dict(post.get("results") or {})
    for p in platforms:
        try:
            results[p] = {"instagram": instagram, "tiktok": tiktok}[p](post)
        except Exception as e:
            results[p] = {"ok": False, "error": str(e)[:300]}
    return results
