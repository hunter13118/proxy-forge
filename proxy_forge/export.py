"""Print output: 3x3 sheets of 2.5 x 3.5 in cards at 300 dpi in a PDF (US Letter or A4) with cut marks in the margins, or a ZIP of the card pictures."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from .render import H, W

PAPER = {"letter": (2550, 3300), "a4": (2480, 3508)}


def sheets(images: list[Path], paper: str = "letter") -> list[Image.Image]:
    pw, ph = PAPER.get(paper, PAPER["letter"])
    ox, oy = (pw - 3 * W) // 2, (ph - 3 * H) // 2
    pages = []
    for start in range(0, len(images), 9):
        page = Image.new("RGB", (pw, ph), "white")
        d = ImageDraw.Draw(page)
        for n, p in enumerate(images[start:start + 9]):
            with Image.open(p) as im:
                page.paste(im.convert("RGB"), (ox + (n % 3) * W, oy + (n // 3) * H))
        for i in range(4):                                                    # cut marks: short ticks in the margins at every card edge
            x, y = ox + i * W, oy + i * H
            d.line((x, max(0, oy - 40), x, oy - 8), fill="#888", width=2)
            d.line((x, oy + 3 * H + 8, x, min(ph, oy + 3 * H + 40)), fill="#888", width=2)
            d.line((max(0, ox - 40), y, ox - 8, y), fill="#888", width=2)
            d.line((ox + 3 * W + 8, y, min(pw, ox + 3 * W + 40), y), fill="#888", width=2)
        pages.append(page)
    return pages


def pdf_bytes(images: list[Path], paper: str = "letter") -> bytes:
    pages = sheets(images, paper)
    if not pages:
        raise ValueError("no cards to print")
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", resolution=300.0, save_all=True, append_images=pages[1:])
    return buf.getvalue()


def zip_bytes(named: list[tuple[str, Path]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name, p in named:
            z.write(p, name)
    return buf.getvalue()
