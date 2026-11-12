"""
Reference photos -> words. Anima has no image-prompt adapter (the studio's notes: "who is who comes from the words and, later, a LoRA"), so a person in the user's photos is
described by a local vision model, as Danbooru-style tags plus a sentence, and those words go into every prompt the person appears in. The description is shown to the user, who
can edit it. The photos never leave this machine (the studio runs here) and are never committed.
"""
from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

from PIL import Image, ImageOps

from .studio import Studio

log = logging.getLogger("references")

ASK = (
    "These photos show one person. Describe ONLY how they look, for an anime illustrator, so a drawing of them is recognisable: hair colour, length and style; eye colour; glasses; "
    "facial hair; skin tone; build; apparent age group; one or two distinctive features (freckles, dimples, a beard, a hat). Do not guess a name or any identity, and do not describe "
    'the background. Answer with JSON only: {"count_tag": "1boy" or "1girl" or "1other", "tags": ["short Danbooru-style appearance tags, e.g. short black hair, brown eyes, round '
    'glasses, stubble"], "sentence": "one plain sentence describing their look"}'
)


def _b64(im: Image.Image, longest: int = 768) -> str:
    im = im.convert("RGB")
    im.thumbnail((longest, longest))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def describe(photos: list[Path], studio: Studio) -> dict:
    """Appearance of the person in the photos, as {count_tag, tags, sentence}, from the studio's vision model (which is let go of right after). Raises if the studio is not reachable."""
    images = [_b64(ImageOps.exif_transpose(Image.open(p))) for p in photos[:4]]
    out = studio.chat_json(ASK, images=images, keep_alive="0", timeout=300, temperature=0.2)
    tags = [str(t).strip().lower() for t in out.get("tags", []) if str(t).strip()][:14]
    count = str(out.get("count_tag", "1other")).strip().lower()
    return {"count_tag": count if count in ("1boy", "1girl", "1other") else "1other", "tags": tags, "sentence": str(out.get("sentence", "")).strip()}
