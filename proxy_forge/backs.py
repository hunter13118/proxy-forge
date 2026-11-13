"""
Card backs: the official Magic back (Scryfall hosts it), a few funny ones drawn here (nothing to download, all original artwork in the style of other games' backs), the owner's own
image, and an AI-drawn one (the drawing itself is the engine's; this module only frames it).

Every back is a 750x1050 RGB picture, the same size as a front, so the duplex sheets (export.py) treat fronts and backs alike. The official back is fetched once into `scans/`.
"""
from __future__ import annotations

import io
import math
import random
from pathlib import Path

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from . import config, scans
from .scryfall import HEADERS

W, H = 750, 1050
MTG_BACK_URL = "https://backs.scryfall.io/png/0/a/0aeebaf5-8c7d-4636-9e82-8c27447861f7.png"      # Scryfall's `card_back_id` of every ordinary card
FUNNY = [
    {"id": "swirl", "name": "Mana swirl", "blurb": "Brown, gold-ringed, five colours round an oval: the look of Magic's own back."},
    {"id": "ball", "name": "Monster ball", "blurb": "Red-and-white capture ball on blue: the look of a certain pocket-monster game."},
    {"id": "eye", "name": "Eye of the duelist", "blurb": "A watching eye in a bronze whirl: the look of a certain card-duelling anime."},
    {"id": "ink", "name": "Inkwell", "blurb": "Deep purple, a golden ink drop and stars: the look of a certain inky Disney game."},
    {"id": "duck", "name": "Rubber duck", "blurb": "Polka dots and a very serious duck."},
    {"id": "tax", "name": "Tax form", "blurb": "Schedule C. Your opponents will never look at the back of your deck again."},
]


def _canvas(scale: int = 2) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", (W * scale, H * scale), "#000")
    return im, ImageDraw.Draw(im)


def _radial(size, inner: str, outer: str) -> Image.Image:
    g = Image.radial_gradient("L").resize(size)
    return ImageOps.colorize(g, inner, outer)


def _finish(im: Image.Image) -> Image.Image:
    return im.resize((W, H), Image.LANCZOS)


def _frame(d, s: int, colour: str, inset: int = 30, width: int = 8, radius: int = 40) -> None:
    d.rounded_rectangle((inset * s, inset * s, (W - inset) * s, (H - inset) * s), radius * s, outline=colour, width=width * s)


def _ring(d, cx, cy, r, colour, width):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=colour, width=width)


def _disc(d, cx, cy, r, fill, outline=None, width=0):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=outline, width=width)


def draw_swirl() -> Image.Image:
    s = 2
    im = _radial((W * s, H * s), "#7a4a24", "#2a140a")
    rnd = random.Random(7)
    d = ImageDraw.Draw(im, "RGBA")
    for _ in range(900):                                                    # mottled parchment
        x, y, r = rnd.randrange(W * s), rnd.randrange(H * s), rnd.randrange(6, 40) * s
        d.ellipse((x - r, y - r, x + r, y + r), fill=(60, 30, 10, rnd.randrange(6, 20)))
    _frame(d, s, "#d9b25a", 22, 6, 46)
    _frame(d, s, "#5a3512", 36, 4, 38)
    cx, cy = W * s // 2, H * s // 2
    d.ellipse((cx - 250 * s, cy - 390 * s, cx + 250 * s, cy + 390 * s), fill=(18, 10, 6, 235), outline="#d9b25a", width=7 * s)
    d.ellipse((cx - 232 * s, cy - 372 * s, cx + 232 * s, cy + 372 * s), outline="#8a6428", width=3 * s)
    for i, c in enumerate(("#f4efd8", "#2f78c9", "#2b2622", "#d6422f", "#2f9a58")):      # the five colours of mana, round a hub
        a = -math.pi / 2 + i * 2 * math.pi / 5
        x, y = cx + math.cos(a) * 150 * s, cy + math.sin(a) * 150 * s
        _disc(d, x, y, 58 * s, c, "#d9b25a", 5 * s)
    for k in range(5):
        a = -math.pi / 2 + k * 2 * math.pi / 5
        b = a + 2 * math.pi * 2 / 5
        d.line((cx + math.cos(a) * 150 * s, cy + math.sin(a) * 150 * s, cx + math.cos(b) * 150 * s, cy + math.sin(b) * 150 * s), fill=(217, 178, 90, 150), width=3 * s)
    _disc(d, cx, cy, 34 * s, "#d9b25a", "#2a140a", 4 * s)
    return _finish(im)


def draw_ball() -> Image.Image:
    s = 2
    im = Image.new("RGB", (W * s, H * s), "#1f3f93")
    d = ImageDraw.Draw(im, "RGBA")
    for i in range(-H, W + H, 70):                                          # diagonal stripes
        d.line((i * s, 0, (i + H) * s, H * s), fill=(255, 255, 255, 16), width=26 * s)
    _frame(d, s, "#ffd23a", 20, 10, 46)
    cx, cy, r = W * s // 2, H * s // 2, 250 * s
    _disc(d, cx, cy, r + 14 * s, "#10151f")
    d.pieslice((cx - r, cy - r, cx + r, cy + r), 180, 360, fill="#e63a30")
    d.pieslice((cx - r, cy - r, cx + r, cy + r), 0, 180, fill="#f6f6f6")
    d.rectangle((cx - r, cy - 22 * s, cx + r, cy + 22 * s), fill="#10151f")
    _disc(d, cx, cy, 72 * s, "#10151f")
    _disc(d, cx, cy, 52 * s, "#f6f6f6", "#9aa3b2", 5 * s)
    return _finish(im)


def draw_eye() -> Image.Image:
    s = 2
    im = _radial((W * s, H * s), "#c78a3e", "#3a1c08")
    d = ImageDraw.Draw(im, "RGBA")
    cx, cy = W * s // 2, H * s // 2
    for k in range(0, 360, 6):                                              # a whirl of rays
        a = math.radians(k)
        d.line((cx, cy, cx + math.cos(a) * 900 * s, cy + math.sin(a) * 900 * s), fill=(255, 220, 150, 22 if k % 12 else 40), width=3 * s)
    for r in (360, 300, 240):
        _ring(d, cx, cy, r * s, (60, 30, 10, 200), 6 * s)
    _frame(d, s, "#e6c273", 22, 8, 46)
    d.polygon([(cx - 280 * s, cy), (cx, cy - 170 * s), (cx + 280 * s, cy), (cx, cy + 170 * s)], fill=(250, 244, 226, 255), outline=(40, 20, 8, 255))
    _disc(d, cx, cy, 112 * s, "#2a6f8f", "#10202a", 8 * s)
    _disc(d, cx, cy, 52 * s, "#05080a")
    _disc(d, cx - 30 * s, cy - 34 * s, 16 * s, "#ffffff")
    d.line((cx - 280 * s, cy, cx - 340 * s, cy + 40 * s), fill="#2a140a", width=8 * s)
    return _finish(im)


def draw_ink() -> Image.Image:
    s = 2
    im = _radial((W * s, H * s), "#5b2a8f", "#1a0b33")
    d = ImageDraw.Draw(im, "RGBA")
    rnd = random.Random(11)
    for _ in range(120):                                                    # stars
        x, y, r = rnd.randrange(W * s), rnd.randrange(H * s), rnd.randrange(2, 7) * s
        d.polygon([(x, y - r * 2), (x + r, y - r), (x + r * 2, y), (x + r, y + r), (x, y + r * 2), (x - r, y + r), (x - r * 2, y), (x - r, y - r)], fill=(255, 230, 150, rnd.randrange(60, 200)))
    _frame(d, s, "#e8c46a", 24, 7, 46)
    cx, cy = W * s // 2, H * s // 2
    d.polygon([(cx, cy - 260 * s), (cx + 150 * s, cy + 40 * s), (cx - 150 * s, cy + 40 * s)], fill="#e8c46a")
    _disc(d, cx, cy + 80 * s, 160 * s, "#e8c46a")
    _disc(d, cx - 50 * s, cy + 30 * s, 36 * s, (255, 247, 210, 180))
    _ring(d, cx, cy + 80 * s, 190 * s, (232, 196, 106, 110), 4 * s)
    return _finish(im)


def draw_duck() -> Image.Image:
    s = 2
    im = Image.new("RGB", (W * s, H * s), "#25b0b0")
    d = ImageDraw.Draw(im, "RGBA")
    for y in range(0, H + 80, 80):
        for x in range(((y // 80) % 2) * 40, W + 80, 80):
            _disc(d, x * s, y * s, 16 * s, (255, 255, 255, 70))
    _frame(d, s, "#ffffff", 22, 12, 46)
    cx, cy = W * s // 2, H * s // 2
    _disc(d, cx, cy + 90 * s, 190 * s, "#ffd21f", "#c99b00", 6 * s)             # body
    _disc(d, cx + 100 * s, cy - 120 * s, 105 * s, "#ffd21f", "#c99b00", 6 * s)  # head
    d.polygon([(cx + 190 * s, cy - 125 * s), (cx + 290 * s, cy - 100 * s), (cx + 190 * s, cy - 75 * s)], fill="#ff8a1f")
    _disc(d, cx + 120 * s, cy - 150 * s, 14 * s, "#161616")
    d.pieslice((cx - 170 * s, cy + 10 * s, cx + 20 * s, cy + 170 * s), 200, 340, fill="#f2b800")
    return _finish(im)


def draw_tax() -> Image.Image:
    from . import render
    s = 2
    im = Image.new("RGB", (W * s, H * s), "#f3f0e4")
    d = ImageDraw.Draw(im)
    ink, green = "#2a2a2a", "#3b6b44"
    d.rectangle((0, 0, W * s, 150 * s), fill=green)
    d.text((40 * s, 50 * s), "FORM 1040-C", font=render.font({}, "title", 62 * s), fill="#f3f0e4")
    d.text((40 * s, 112 * s), "Profit or Loss From Playing Cards", font=render.font({}, "body", 26 * s), fill="#dfe8d8")
    for i in range(14):
        y = (190 + i * 58) * s
        d.line((40 * s, y, (W - 40) * s, y), fill="#b9b49f", width=2 * s)
        d.rectangle((40 * s, y - 40 * s, 80 * s, y - 6 * s), outline=ink, width=2 * s)
        d.rectangle(((W - 190) * s, y - 40 * s, (W - 40) * s, y - 6 * s), outline=ink, width=2 * s)
        d.line((100 * s, y - 20 * s, (200 + (i * 53) % 330) * s, y - 20 * s), fill="#8e8a76", width=3 * s)
    d.text((40 * s, 1000 * s), "Do not staple. Do not bluff.", font=render.font({}, "body", 24 * s), fill=ink)
    return _finish(im)


DRAW = {"swirl": draw_swirl, "ball": draw_ball, "eye": draw_eye, "ink": draw_ink, "duck": draw_duck, "tax": draw_tax}


def funny(bid: str) -> Image.Image:
    """A funny back by id, drawn once and kept in `backs/` on G:."""
    if bid not in DRAW:
        raise KeyError(bid)
    f = config.folder("backs") / f"funny-{bid}.png"
    if not f.exists():
        DRAW[bid]().save(f, "PNG")
    return Image.open(f).convert("RGB")


def cover(im: Image.Image, size=(W, H)) -> Image.Image:
    """Any picture fitted to the card shape: scaled to cover, centred, the overflow trimmed (a back is a picture, so a crop is the honest way to fit it)."""
    return ImageOps.fit(im.convert("RGB"), size, Image.LANCZOS, centering=(0.5, 0.5))


def official(transport: httpx.BaseTransport | None = None) -> Image.Image:
    """Magic's own card back, from Scryfall (fetched once), with the rounded corners squared in the border colour like the front scans."""
    f = config.folder("backs") / "official-mtg.png"
    if not f.exists():
        with httpx.Client(timeout=60, follow_redirects=True, transport=transport) as c:
            r = c.get(MTG_BACK_URL, headers={"User-Agent": HEADERS["User-Agent"], "Accept": "image/*"})
        r.raise_for_status()
        Image.open(io.BytesIO(r.content)).verify()
        tmp = f.with_suffix(".part")
        tmp.write_bytes(r.content)
        tmp.replace(f)
    return scans.official(f, mark=False)


def ai_frame(art: Image.Image) -> Image.Image:
    """A drawn picture as a card back: the art inside a thin dark border with a fine gold line, so it reads as a card and trims cleanly."""
    s = 2
    out = Image.new("RGB", (W * s, H * s), "#0b0b0b")
    inner = (34 * s, 34 * s, (W - 34) * s, (H - 34) * s)
    pic = cover(art, (inner[2] - inner[0], inner[3] - inner[1]))
    mask = Image.new("L", pic.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, pic.width - 1, pic.height - 1), 26 * s, fill=255)
    out.paste(pic, inner[:2], mask)
    ImageDraw.Draw(out).rounded_rectangle(inner, 26 * s, outline="#c9a24a", width=3 * s)
    return out.resize((W, H), Image.LANCZOS)
