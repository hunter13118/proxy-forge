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


def best_layout(paper: str = "a4", size: str = "mtg", margin_mm: float = 5.0, gap_mm: float = 0.0, turn: str = "auto") -> Layout:
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
    """Short ticks in the margins at every card edge, kept clear of the card block by a few mm."""
    pw, ph = lay.page
    (ox, oy), (cw, ch), g = lay.origin, lay.card, lay.gap
    right, bottom = ox + lay.cols * cw + (lay.cols - 1) * g, oy + lay.rows * ch + (lay.rows - 1) * g
    xs = sorted({ox + i * (cw + g) + off for i in range(lay.cols) for off in (0, cw)})
    ys = sorted({oy + j * (ch + g) + off for j in range(lay.rows) for off in (0, ch)})
    off, ink = _px(0.7), "#777"
    for x in xs:
        if oy - off > 4:
            d.line((x, max(0, oy - off - _px(3.4)), x, oy - off), fill=ink, width=2)
        if bottom + off < ph - 4:
            d.line((x, bottom + off, x, min(ph, bottom + off + _px(3.4))), fill=ink, width=2)
    for y in ys:
        if ox - off > 4:
            d.line((max(0, ox - off - _px(3.4)), y, ox - off, y), fill=ink, width=2)
        if right + off < pw - 4:
            d.line((right + off, y, min(pw, right + off + _px(3.4)), y), fill=ink, width=2)


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


def pages_needed(count: int, paper: str = "a4", **kw) -> int:
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
