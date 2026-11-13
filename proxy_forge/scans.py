"""
Official card images: download once, keep forever, prepare for printing.

Scryfall's image hosts (`cards.scryfall.io`) are not API-rate-limited, so scans are fetched in parallel. The print image is the 745x1040 `png`; the grid thumbnail is `normal`
(488x680 jpg); `art_crop` is for the art-in-a-template style. Files live in `scans/` on G: named `<printing id>-<face>-<hi|lo>.<kind>`; the hi/lo part is the image status, so when
Scryfall upgrades a low-resolution scan the next fetch sees a different name and downloads the better one. Everything is written `.part` -> rename and checked with PIL.

`official()` puts a scan on the 750x1050 proxy card without resampling it: it is centred, not stretched, and the transparent rounded corners are filled with the card's own border
colour so it prints square. Scryfall asks that images are not stretched, blurred or sharpened; padding needs none of that.
"""
from __future__ import annotations

import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from . import config
from .scryfall import HEADERS, SEPARATE_FACES

log = logging.getLogger("scans")
W, H = 750, 1050
KINDS = {"png": "png", "normal": "jpg", "art_crop": "jpg"}
MARK = "PROXY  ·  not for sale"


def scan_dir() -> Path:
    return config.folder("scans")


def card_of(printing: dict) -> dict:
    return json.loads(printing["json"]) if isinstance(printing.get("json"), str) else printing


def image_uris(card: dict, face: int = 0) -> dict:
    faces = card.get("card_faces") or []
    if faces and card.get("layout") in SEPARATE_FACES and faces[min(face, len(faces) - 1)].get("image_uris"):
        return faces[min(face, len(faces) - 1)]["image_uris"]
    return card.get("image_uris") or (faces[0].get("image_uris") if faces else None) or {}


def path_for(printing: dict, face: int = 0, kind: str = "png") -> Path:
    q = "hi" if printing.get("image_status") == "highres_scan" else "lo"
    return scan_dir() / f"{printing['id']}-{face}-{q}.{KINDS[kind]}" if kind == "png" else scan_dir() / f"{printing['id']}-{face}-{q}-{kind}.{KINDS[kind]}"


def fetch(printing: dict, face: int = 0, kind: str = "png", transport: httpx.BaseTransport | None = None) -> Path:
    """The image on disk, downloaded if it is not there yet."""
    out = path_for(printing, face, kind)
    if out.exists():
        return out
    url = image_uris(card_of(printing), face).get(kind)
    if not url:
        raise RuntimeError(f"Scryfall has no {kind} image for {printing.get('id')} (face {face})")
    with httpx.Client(timeout=60, follow_redirects=True, transport=transport) as c:
        r = c.get(url, headers={"User-Agent": HEADERS["User-Agent"], "Accept": "image/*"})
    r.raise_for_status()
    Image.open(io.BytesIO(r.content)).verify()
    tmp = out.with_suffix(out.suffix + ".part")
    tmp.write_bytes(r.content)
    tmp.replace(out)
    return out


def fetch_many(jobs: list[tuple[dict, int, str]], progress=lambda done, total: None, transport=None, workers: int = 4) -> list[str]:
    """Download several images, four at a time. Returns the errors (an empty list when all arrived)."""
    errors: list[str] = []
    done = 0

    def one(j):
        try:
            fetch(*j, transport=transport)
        except Exception as e:
            return f"{j[0].get('id')}: {e}"
        return None
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(one, jobs):
            done += 1
            if r:
                errors.append(r)
            progress(done, len(jobs))
    return errors


def _border_colour(im: Image.Image) -> tuple[int, int, int]:
    """The colour of the card's outer ring: the median of opaque pixels a few pixels in from each edge."""
    rgba = im.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()
    samples = []
    for t in (4, 7):
        for x in range(w // 5, w - w // 5, 9):
            samples += [px[x, t], px[x, h - 1 - t]]
        for y in range(h // 5, h - h // 5, 9):
            samples += [px[t, y], px[w - 1 - t, y]]
    samples = [s for s in samples if s[3] > 250] or [(0, 0, 0, 255)]
    return tuple(sorted(s[i] for s in samples)[len(samples) // 2] for i in range(3))


def official(scan: Path, mark: bool = True) -> Image.Image:
    """The scan on a 750x1050 canvas: centred (no resampling), corners squared in the border colour, with the small proxy line in the bottom border."""
    with Image.open(scan) as src:
        src.load()
        im = src.convert("RGBA")
    colour = _border_colour(im)
    canvas = Image.new("RGBA", (W, H), colour + (255,))
    if im.width > W or im.height > H:                                         # never expected (745x1040); keep it whole if it is
        im.thumbnail((W, H), Image.LANCZOS)
    canvas.alpha_composite(im, ((W - im.width) // 2, (H - im.height) // 2))
    out = canvas.convert("RGB")
    if mark:
        d = ImageDraw.Draw(out, "RGBA")
        lum = 0.299 * colour[0] + 0.587 * colour[1] + 0.114 * colour[2]
        ink = (235, 235, 235, 235) if lum < 110 else (30, 30, 30, 235)
        from . import render
        d.text((W / 2, H - 10), MARK, font=render.font({}, "body", 13), fill=ink, anchor="mm")
    return out
