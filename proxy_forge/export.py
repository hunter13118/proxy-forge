"""Print output: cards packed onto PDF sheets (A4 or US Letter, 300 dpi, exact physical size) with cut marks in the margins, or a ZIP of the card pictures.

Packing: `best_layout` tries the card upright and turned 90 degrees and keeps whichever puts more cards on the page inside the printer-safe margin. With cards touching (no gap) one set of straight cuts separates them, so nothing is wasted between cards. On A4 that is 3 x 3 = 9 per sheet whatever the margin: the page area allows at most 11 and the leftover strips (about 20 x 30 mm) are too small for another card.
"""
from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

DPI = 300
MM = 25.4
PAPER_MM = {"letter": (215.9, 279.4), "a4": (210.0, 297.0)}
CARD_MM = {"mtg": (63.0, 88.0), "inch": (63.5, 88.9)}       # real Magic card, or the 2.5 x 3.5 in the card pictures are drawn at
PAPER = {name: (round(w / MM * DPI), round(h / MM * DPI)) for name, (w, h) in PAPER_MM.items()}          # px at 300 dpi: letter 2550x3300, a4 2480x3508
BASICS = {"plains", "island", "swamp", "mountain", "forest", "wastes"}


def _px(mm: float) -> int:
    return round(mm / MM * DPI)


def is_basic_land(name: str) -> bool:
    n = name.lower().removeprefix("snow-covered ").strip()
    return n in BASICS


@dataclass(frozen=True)
class Layout:
    page: tuple[int, int]                 # px
    card: tuple[int, int]                 # px as placed on the page (already turned when `turned`)
    cols: int
    rows: int
    turned: bool                          # cards are rotated 90 degrees on the page
    gap: int                              # px between cards (0: they share cut lines)
    origin: tuple[int, int]               # top-left of the card block, centred on the page

    @property
    def per_page(self) -> int:
        return self.cols * self.rows

    def cell(self, n: int) -> tuple[int, int]:
        return self.origin[0] + (n % self.cols) * (self.card[0] + self.gap), self.origin[1] + (n // self.cols) * (self.card[1] + self.gap)


def best_layout(paper: str = "letter", size: str = "mtg", margin_mm: float = 5.0, gap_mm: float = 0.0, turn: str = "auto") -> Layout:
    """The arrangement with the most cards per page. `margin_mm` is the blank border the printer cannot reach; `turn` is auto | never | always."""
    pw, ph = PAPER.get(paper, PAPER["letter"])
    cw, ch = (_px(v) for v in CARD_MM.get(size, CARD_MM["mtg"]))
    m, gap = _px(margin_mm), _px(gap_mm)
    best = None
    for turned in ((False, True) if turn == "auto" else (turn == "always",)):
        w, h = (ch, cw) if turned else (cw, ch)
        cols, rows = (pw - 2 * m + gap) // (w + gap), (ph - 2 * m + gap) // (h + gap)
        if cols < 1 or rows < 1:
            continue
        if best is None or cols * rows > best[0] * best[1]:
            best = (cols, rows, turned, w, h)
    if best is None:
        raise ValueError("a card does not fit on the page inside that margin")
    cols, rows, turned, w, h = best
    ox, oy = (pw - (cols * w + (cols - 1) * gap)) // 2, (ph - (rows * h + (rows - 1) * gap)) // 2
    return Layout((pw, ph), (w, h), cols, rows, turned, gap, (ox, oy))


def _cut_marks(d: ImageDraw.ImageDraw, lay: Layout) -> None:
    """Ticks at every card edge, running from just outside the card block out to the edge of the page (as far as the page goes; a printer clips what it cannot reach)."""
    pw, ph = lay.page
    (ox, oy), (cw, ch), g = lay.origin, lay.card, lay.gap
    right, bottom = ox + lay.cols * cw + (lay.cols - 1) * g, oy + lay.rows * ch + (lay.rows - 1) * g
    xs = sorted({ox + i * (cw + g) + off for i in range(lay.cols) for off in (0, cw)})
    ys = sorted({oy + j * (ch + g) + off for j in range(lay.rows) for off in (0, ch)})
    off, ink = _px(0.7), "#777"
    for x in xs:
        if oy - off > 4:
            d.line((x, 0, x, oy - off), fill=ink, width=2)
        if bottom + off < ph - 4:
            d.line((x, bottom + off, x, ph), fill=ink, width=2)
    for y in ys:
        if ox - off > 4:
            d.line((0, y, ox - off, y), fill=ink, width=2)
        if right + off < pw - 4:
            d.line((right + off, y, pw, y), fill=ink, width=2)


def sheets(images: list[Path], paper: str = "letter", size: str = "mtg", margin_mm: float = 5.0, gap_mm: float = 0.0, turn: str = "auto", marks: bool = True) -> list[Image.Image]:
    lay = best_layout(paper, size, margin_mm, gap_mm, turn)
    cw, ch = (lay.card[1], lay.card[0]) if lay.turned else lay.card
    pages, cache = [], {}
    for start in range(0, len(images), lay.per_page):
        page = Image.new("RGB", lay.page, "white")
        for n, p in enumerate(images[start:start + lay.per_page]):
            if p not in cache:                                              # a card printed 4 times is opened and resized once
                with Image.open(p) as im:
                    c = im.convert("RGB")
                    c = c if c.size == (cw, ch) else c.resize((cw, ch), Image.LANCZOS)
                    cache[p] = c.rotate(90, expand=True) if lay.turned else c
            page.paste(cache[p], lay.cell(n))
        if marks:
            _cut_marks(ImageDraw.Draw(page), lay)
        pages.append(page)
    return pages


def pages_needed(count: int, paper: str = "letter", **kw) -> int:
    return math.ceil(count / best_layout(paper, **kw).per_page)


def pdf_bytes(images: list[Path], paper: str = "letter", **kw) -> bytes:
    pages = sheets(images, paper, **kw)
    if not pages:
        raise ValueError("no cards to print")
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", resolution=float(DPI), quality=95, subsampling=0, save_all=True, append_images=pages[1:])
    return buf.getvalue()


def zip_bytes(named: list[tuple[str, Path]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name, p in named:
            z.write(p, name)
    return buf.getvalue()


BLEED_PX = 36                                                          # 1/8 in at 300 dpi: what print shops (MPC and others) ask for


def with_bleed(card: Image.Image, px: int = BLEED_PX, mirror: bool = False) -> Image.Image:
    """The card on a canvas `px` larger on every side (750x1050 -> 822x1122). Bordered cards: the border colour runs on past the cut line. Borderless and full-art cards (`mirror`): the
    outer `px` of the picture is mirrored outward, so the art continues through the cut and no thin edge shows after trimming."""
    from PIL import ImageOps
    w, h = card.size
    card = card.convert("RGB")
    if mirror:
        out = Image.new("RGB", (w + 2 * px, h + 2 * px))
        out.paste(card, (px, px))
        out.paste(ImageOps.mirror(card.crop((0, 0, px, h))), (0, px))
        out.paste(ImageOps.mirror(card.crop((w - px, 0, w, h))), (w + px, px))
        out.paste(ImageOps.flip(card.crop((0, 0, w, px))), (px, 0))
        out.paste(ImageOps.flip(card.crop((0, h - px, w, h))), (px, h + px))
        for cx, cy, box in ((0, 0, (0, 0, px, px)), (w + px, 0, (w - px, 0, w, px)), (0, h + px, (0, h - px, px, h)), (w + px, h + px, (w - px, h - px, w, h))):
            out.paste(ImageOps.flip(ImageOps.mirror(card.crop(box))), (cx, cy))
        return out
    ring = [card.getpixel((x, y)) for x in range(8, w - 8, 12) for y in (3, 6, h - 4, h - 7)] + [card.getpixel((x, y)) for y in range(8, h - 8, 12) for x in (3, 6, w - 4, w - 7)]
    colour = tuple(sorted(c[i] for c in ring)[len(ring) // 2] for i in range(3))
    out = Image.new("RGB", (w + 2 * px, h + 2 * px), colour)
    out.paste(card, (px, px))
    return out


def zip_images(named: list[tuple[str, Image.Image]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name, im in named:
            b = io.BytesIO()
            im.save(b, "PNG", dpi=(300, 300))
            z.writestr(name, b.getvalue())
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------------------------------------------------------------- two-sided printing
#
# The one rule: a back must sit exactly behind its front. Flipping the sheet mirrors it, so on the back page a card's slot is the front slot mirrored across the flip axis, and the
# back picture is turned so that its top edge is the same physical edge as the front's:
#   flip on the LONG edge (like turning a book page; portrait paper): columns mirror, left <-> right. An upright front -> an upright back; a front turned 90 (top edge to the page's left) -> back
#                                                                      turned the other way (top edge to the page's right).
#   flip on the SHORT edge (like a notepad flipped up): rows mirror, top <-> bottom. An upright front -> a back turned 180; a turned front -> a back turned the same way.
# Pages are "as read": the printer's duplex setting (or you, turning the sheet over) does the physical flip, so the PDF does not mirror pictures, it only moves and turns them.

FLIPS = ("long", "short")


def back_cell(lay: Layout, n: int, flip: str, dx: int = 0, dy: int = 0) -> tuple[int, int]:
    """Where the back of the card in front slot `n` goes: the front slot mirrored across the flip axis, plus the owner's alignment shift (px)."""
    x, y = lay.cell(n)
    w, h = lay.card
    pw, ph = lay.page
    return ((pw - x - w, y) if flip == "long" else (x, ph - y - h))[0] + dx, ((pw - x - w, y) if flip == "long" else (x, ph - y - h))[1] + dy


def back_angle(lay: Layout, flip: str) -> int:
    """PIL rotation (counter-clockwise degrees) of an upright back picture so its top edge lines up with the front's top edge after the flip."""
    if flip == "long":
        return 270 if lay.turned else 0
    return 90 if lay.turned else 180


def duplex_pages(pairs: list[tuple[Path, Path | None]], paper: str = "letter", size: str = "mtg", margin_mm: float = 5.0, gap_mm: float = 0.0, turn: str = "auto", marks: bool = True,
                 flip: str = "long", dx_mm: float = 0.0, dy_mm: float = 0.0) -> tuple[list[Image.Image], list[Image.Image]]:
    """(front pages, back pages), page i of each belonging to the same sheet. `pairs` is (front picture, back picture or None)."""
    if flip not in FLIPS:
        raise ValueError("flip must be long or short")
    lay = best_layout(paper, size, margin_mm, gap_mm, turn)
    cw, ch = (lay.card[1], lay.card[0]) if lay.turned else lay.card
    dx, dy = _px(dx_mm), _px(dy_mm)
    cache: dict = {}

    def get(p: Path, angle: int) -> Image.Image:
        if (p, angle) not in cache:
            with Image.open(p) as im:
                c = im.convert("RGB")
                c = c if c.size == (cw, ch) else c.resize((cw, ch), Image.LANCZOS)
                cache[(p, angle)] = c.rotate(angle, expand=True) if angle else c
        return cache[(p, angle)]
    fronts, backs = [], []
    for start in range(0, len(pairs), lay.per_page):
        fp, bp = Image.new("RGB", lay.page, "white"), Image.new("RGB", lay.page, "white")
        for n, (front, back) in enumerate(pairs[start:start + lay.per_page]):
            fp.paste(get(front, 90 if lay.turned else 0), lay.cell(n))
            if back is not None:
                bp.paste(get(back, back_angle(lay, flip)), back_cell(lay, n, flip, dx, dy))
        if marks:
            _cut_marks(ImageDraw.Draw(fp), lay)
        fronts.append(fp)
        backs.append(bp)
    return fronts, backs


def duplex_order(fronts: list[Image.Image], backs: list[Image.Image], mode: str, part: str = "all", reverse_backs: bool = False) -> list[Image.Image]:
    """The page order of the PDF.
    auto   : front 1, back 1, front 2, back 2 ...  (the printer prints both sides of each sheet itself: set 2-sided printing to the same flip edge)
    manual : all fronts, then all backs  (print the fronts, put the stack back in, print the backs; `reverse_backs` for printers that stack their output in the opposite order)
    `part` (manual only) gives just the fronts or just the backs, to save as two PDFs."""
    if mode == "auto":
        return [p for pair in zip(fronts, backs) for p in pair]
    if mode != "manual":
        return fronts
    b = backs[::-1] if reverse_backs else backs
    return fronts if part == "fronts" else b if part == "backs" else fronts + b


def pages_pdf(pages: list[Image.Image]) -> bytes:
    if not pages:
        raise ValueError("no cards to print")
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", resolution=float(DPI), quality=95, subsampling=0, save_all=True, append_images=pages[1:])
    return buf.getvalue()


def test_sheets(paper: str = "letter", size: str = "mtg", margin_mm: float = 5.0, turn: str = "auto", flip: str = "long", dx_mm: float = 0.0, dy_mm: float = 0.0) -> list[Image.Image]:
    """Two pages for checking a printer before printing a deck: slot numbers and a TOP arrow on the front, the same on the back where each back belongs (mirrored slot, turned to match),
    and a cross at the centre of every slot on both sides. Print both sides, hold the sheet to a window: the crosses must coincide and the numbers must read the same way up."""
    from . import render
    lay = best_layout(paper, size, margin_mm, 0.0, turn)
    cw, ch = lay.card
    big, small = render.font({}, "title", 120), render.font({}, "body", 34)

    def card(n: int, side: str) -> Image.Image:
        c = Image.new("RGB", (750, 1050), "white" if side == "front" else "#eef3ff")
        d = ImageDraw.Draw(c)
        d.rectangle((6, 6, 743, 1043), outline="black", width=4)
        d.text((375, 130), "TOP", font=big, fill="black", anchor="mm")
        d.polygon([(375, 20), (320, 100), (430, 100)], fill="black")
        d.text((375, 525), str(n + 1), font=render.font({}, "title", 300), fill="#bbb", anchor="mm")
        d.line((335, 525, 415, 525), fill="red", width=5)
        d.line((375, 485, 375, 565), fill="red", width=5)
        d.text((375, 930), side.upper(), font=big, fill="black" if side == "front" else "#2a4fb0", anchor="mm")
        d.text((375, 1000), f"slot {n + 1} · {paper.upper()} · flip on the {flip} edge", font=small, fill="#555", anchor="mm")
        return c
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        pairs = []
        for n in range(lay.per_page):
            f, b = Path(td) / f"f{n}.png", Path(td) / f"b{n}.png"
            card(n, "front").save(f)
            card(n, "back").save(b)
            pairs.append((f, b))
        fronts, backs = duplex_pages(pairs, paper, size, margin_mm, 0.0, turn, True, flip, dx_mm, dy_mm)
        fronts[0].load(); backs[0].load()
    return [fronts[0], backs[0]]
