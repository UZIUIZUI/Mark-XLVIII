"""Point the camera at something and find out what it is — and where to get it.

WHY THIS EXISTS SEPARATELY FROM screen_process
screen_process hands a picture to the live conversation model, which can say
what it sees but has no web access in that moment. So "what is this?" worked
and "find me this one" did not: JARVIS could describe a shoe and then search
for the words "a white trainer", which finds nothing.

This does both halves in a single call, because the model doing the looking is
also the model doing the searching: the image and Google's index are in the
same request. That is what Google Lens does, and it needs no extra account —
the Gemini key already in config covers it.

WHAT IT IS NOT
Lens proper can find the exact photograph — the page a specific image was
published on. This recognises what is IN the picture and searches for that.
For objects, products, plants, landmarks and printed text it lands in the same
place. For "where did this photo come from" it does not, and the prompt tells
JARVIS to say so rather than pretend.
"""

from __future__ import annotations

from actions.screen_processor import (
    _capture_camera,
    _capture_screen,
    _get_api_key,
)

# What to ask about the picture, per intent. Each one insists on naming the
# thing precisely, because a vague answer is exactly the failure this replaces.
_PROMPTS = {
    "identify": (
        "Identify what is in this image as precisely as you can — brand, model, "
        "title, species, or the exact text printed on it. Search the web to "
        "confirm before answering. Then say in two or three short sentences what "
        "it is and one genuinely useful fact about it. If you cannot tell what it "
        "is, say that plainly instead of guessing."
    ),
    "buy": (
        "Identify the exact product in this image — brand and model. Search the "
        "web for what it currently costs and where it can be bought. Answer in "
        "three short sentences: what it is, the going price, and where. If the "
        "picture does not show enough to identify the exact model, say so and "
        "name what you could make out."
    ),
    "similar": (
        "Identify what is in this image, then search for where more pictures of "
        "it can be found. Say what it is and name the best sources, in two short "
        "sentences."
    ),
    "text": (
        "Read all text visible in this image, exactly as printed. Then say in one "
        "sentence what the text is from or about. If some of it is illegible, say "
        "which part."
    ),
}


def _capture(source: str) -> tuple[bytes, str]:
    if str(source).lower().strip() in ("camera", "webcam", "cam"):
        return _capture_camera()
    return _capture_screen()


def lens_search(parameters: dict, response=None, player=None, **_kw) -> str:
    """Look at the camera or the screen and search the web for what is there."""
    params = parameters or {}
    source = params.get("source", "camera")
    intent = str(params.get("intent", "identify")).lower().strip()
    extra  = str(params.get("question", "")).strip()

    prompt = _PROMPTS.get(intent, _PROMPTS["identify"])
    if extra:
        # The user's own wording wins — they may want something the fixed
        # prompts do not cover ("is this the older model?").
        prompt = (f"{prompt}\n\nThe user specifically asks: {extra}\n"
                  f"Answer that question above all else.")

    try:
        image_bytes, mime_type = _capture(source)
    except Exception as e:
        return f"Could not capture the image: {e}"

    if player:
        try:
            player.write_log(f"[Lens] Looking at the {source}...")
        except Exception:
            pass

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=_get_api_key())
        result = client.models.generate_content(
            model="gemini-flash-latest",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt,
            ],
            # The whole point: the model that sees the picture can also search.
            config={"tools": [{"google_search": {}}]},
        )
    except Exception as e:
        msg = str(e)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            return ("The image lookup is out of quota for now. I can still look "
                    "at it and describe what I see — ask me to do that instead.")
        if "503" in msg or "UNAVAILABLE" in msg:
            return ("The image service is overloaded at the moment. Worth trying "
                    "again in a minute.")
        return f"Image lookup failed: {e}"

    text = ""
    try:
        for part in result.candidates[0].content.parts:
            if getattr(part, "text", ""):
                text += part.text
    except Exception:
        pass

    text = text.strip()
    if not text:
        return "I could not make anything out in that image."

    # Show it on the HUD as well: a model number or a price is worth reading,
    # not just hearing once.
    if player:
        try:
            player.show_content(f"LENS — {source}", text)
        except Exception:
            pass

    return text
