"""More funny backs (pizza, cat, bat, clockwork, synthwave, d20, circuit board). All original, drawn with PIL at 2x and shrunk; the helpers are backs.py's."""
from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from . import backs as B

W, H = B.W, B.H
S = 2


def _new(colour: str):
    im = Image.new("RGB", (W * S, H * S), colour)
    return im, ImageDraw.Draw(im, "RGBA")


def draw_pizza() -> Image.Image:
    im, d = _new("#b8352b")
    for y in range(0, H, 100):                                              # a checked tablecloth
        for x in range(0, W, 100):
            if (x // 100 + y // 100) % 2 == 0:
                d.rectangle((x * S, y * S, (x + 100) * S, (y + 100) * S), fill="#f2ece0")
    B._frame(d, S, "#2a2a2a", 22, 10, 46)
    cx, cy = W * S // 2, H * S // 2
    B._disc(d, cx, cy, 300 * S, "#c58a3a")
    B._disc(d, cx, cy, 262 * S, "#f0b03a")
    B._disc(d, cx, cy, 238 * S, "#e8c15a")
    rnd = random.Random(5)
    for _ in range(14):
        a, r = rnd.random() * 2 * math.pi, rnd.random() * 190
        B._disc(d, cx + math.cos(a) * r * S, cy + math.sin(a) * r * S, 34 * S, "#b3261e", "#8c1a14", 3 * S)
    for _ in range(18):
        a, r = rnd.random() * 2 * math.pi, rnd.random() * 215
        B._disc(d, cx + math.cos(a) * r * S, cy + math.sin(a) * r * S, 9 * S, "#2f8a3a")
    for k in range(8):
        a = k * math.pi / 4 + math.pi / 8
        d.line((cx, cy, cx + math.cos(a) * 300 * S, cy + math.sin(a) * 300 * S), fill="#8a5a1a", width=3 * S)
    return B._finish(im)


def draw_cat() -> Image.Image:
    im, d = _new("#f2c14e")
    for i in range(0, H + W, 60):
        d.line((0, i * S, W * S, (i - W) * S), fill="#e0aa34", width=14 * S)
    B._frame(d, S, "#3a2a14", 22, 10, 46)
    cx, cy = W * S // 2, H * S // 2
    fur, dark = "#d9d4c8", "#2c2a26"
    d.polygon([(cx - 250 * S, cy - 40 * S), (cx - 215 * S, cy - 320 * S), (cx - 70 * S, cy - 170 * S)], fill=fur, outline=dark)
    d.polygon([(cx + 250 * S, cy - 40 * S), (cx + 215 * S, cy - 320 * S), (cx + 70 * S, cy - 170 * S)], fill=fur, outline=dark)
    d.polygon([(cx - 215 * S, cy - 260 * S), (cx - 195 * S, cy - 150 * S), (cx - 120 * S, cy - 190 * S)], fill="#e9a3a3")
    d.polygon([(cx + 215 * S, cy - 260 * S), (cx + 195 * S, cy - 150 * S), (cx + 120 * S, cy - 190 * S)], fill="#e9a3a3")
    d.ellipse((cx - 270 * S, cy - 230 * S, cx + 270 * S, cy + 250 * S), fill=fur, outline=dark, width=6 * S)
    for sx in (-1, 1):
        ex = cx + sx * 110 * S
        d.ellipse((ex - 62 * S, cy - 60 * S, ex + 62 * S, cy + 40 * S), fill="#f4f0d0", outline=dark, width=5 * S)
        d.rectangle((ex - 62 * S, cy - 60 * S, ex + 62 * S, cy - 24 * S), fill=fur)          # half-closed lids: unimpressed
        d.ellipse((ex - 22 * S, cy - 24 * S, ex + 22 * S, cy + 22 * S), fill=dark)
        for k in (-1, 0, 1):
            d.line((cx + sx * 150 * S, cy + 120 * S + k * 26 * S, cx + sx * 330 * S, cy + 100 * S + k * 50 * S), fill=dark, width=4 * S)
    d.polygon([(cx - 26 * S, cy + 90 * S), (cx + 26 * S, cy + 90 * S), (cx, cy + 126 * S)], fill="#e07b86")
    d.arc((cx - 60 * S, cy + 110 * S, cx, cy + 170 * S), 20, 160, fill=dark, width=5 * S)
    d.arc((cx, cy + 110 * S, cx + 60 * S, cy + 170 * S), 20, 160, fill=dark, width=5 * S)
    return B._finish(im)


def draw_bat() -> Image.Image:
    im = B._radial((W * S, H * S), "#3b2a6b", "#0c0818")
    d = ImageDraw.Draw(im, "RGBA")
    rnd = random.Random(9)
    for _ in range(90):
        B._disc(d, rnd.randrange(W * S), rnd.randrange(H * S), rnd.randrange(2, 5) * S, (255, 255, 255, rnd.randrange(60, 200)))
    B._frame(d, S, "#8e7cc3", 22, 7, 46)
    cx, cy = W * S // 2, H * S // 2 - 60 * S
    B._disc(d, cx, cy, 230 * S, "#f3ecc8")
    for ox, oy, r in ((-70, -50, 40), (60, 40, 55), (-20, 90, 28), (90, -90, 24)):
        B._disc(d, cx + ox * S, cy + oy * S, r * S, "#dcd3a8")
    bx, by = cx, cy + 40 * S
    pts = [(0, -80), (-40, -20), (-300, -150), (-220, 10), (-270, 80), (-150, 50), (-90, 120), (-30, 60), (30, 60), (90, 120), (150, 50), (270, 80), (220, 10), (300, -150), (40, -20)]
    d.polygon([(bx + x * S, by + y * S) for x, y in pts], fill=(18, 12, 30))
    d.polygon([(bx - 40 * S, by - 80 * S), (bx - 22 * S, by - 150 * S), (bx - 6 * S, by - 90 * S)], fill=(18, 12, 30))
    d.polygon([(bx + 40 * S, by - 80 * S), (bx + 22 * S, by - 150 * S), (bx + 6 * S, by - 90 * S)], fill=(18, 12, 30))
    B._disc(d, bx - 16 * S, by - 56 * S, 7 * S, "#ffdf5a")
    B._disc(d, bx + 16 * S, by - 56 * S, 7 * S, "#ffdf5a")
    return B._finish(im)


def draw_gears() -> Image.Image:
    im = B._radial((W * S, H * S), "#7a5a2a", "#241608")
    d = ImageDraw.Draw(im, "RGBA")

    def gear(cx, cy, r, teeth, colour, hole):
        pts = []
        for i in range(teeth * 2):
            a = math.pi * i / teeth
            rr = r if i % 2 == 0 else r * 0.82
            for da in (-0.45, 0.45):
                pts.append((cx + math.cos(a + da * math.pi / teeth) * rr, cy + math.sin(a + da * math.pi / teeth) * rr))
        d.polygon(pts, fill=colour, outline="#2a1a08")
        B._disc(d, cx, cy, r * 0.55, (0, 0, 0, 60))
        B._disc(d, cx, cy, r * hole, "#1a1006", "#d9b25a", 4 * S)
    gear(260 * S, 330 * S, 210 * S, 14, "#b8862e", 0.2)
    gear(560 * S, 560 * S, 250 * S, 16, "#a8782a", 0.22)
    gear(250 * S, 800 * S, 150 * S, 10, "#c9962f", 0.2)
    gear(600 * S, 160 * S, 110 * S, 8, "#c9962f", 0.2)
    B._frame(d, S, "#d9b25a", 22, 8, 46)
    return B._finish(im)


def draw_synth() -> Image.Image:
    im, d = _new("#1a0a3a")
    hor = 640 * S
    for y in range(0, hor, 4 * S):                                          # sky gradient
        t = y / hor
        d.rectangle((0, y, W * S, y + 4 * S), fill=(int(40 + 215 * t), int(10 + 70 * t), int(90 + 40 * (1 - t) + 30 * t)))
    cx, cy = W * S // 2, 430 * S
    B._disc(d, cx, cy, 190 * S, "#ffb84a")
    for k in range(7):                                                      # blinds cut across the sun
        d.rectangle((cx - 200 * S, cy + 20 * S + k * 26 * S, cx + 200 * S, cy + 20 * S + k * 26 * S + (2 + k * 2) * S), fill=(26, 10, 58))
    d.rectangle((0, hor, W * S, H * S), fill="#12062e")
    for i in range(-12, 13):                                                # the grid
        d.line((cx + i * 12 * S, hor, cx + i * 130 * S, H * S), fill="#ff4fd8", width=3 * S)
    for k in range(1, 9):
        d.line((0, hor + (k ** 2) * 6 * S, W * S, hor + (k ** 2) * 6 * S), fill="#ff4fd8", width=3 * S)
    d.line((0, hor, W * S, hor), fill="#7ae8ff", width=5 * S)
    B._frame(d, S, "#7ae8ff", 22, 7, 46)
    return B._finish(im)


def draw_d20() -> Image.Image:
    from . import render
    im, d = _new("#0f5a3a")
    rnd = random.Random(3)
    for _ in range(2500):                                                   # felt
        d.point((rnd.randrange(W * S), rnd.randrange(H * S)), fill=(255, 255, 255, 14))
    B._frame(d, S, "#d9b25a", 22, 7, 46)
    cx, cy, R = W * S // 2, H * S // 2, 280 * S
    hexa = [(cx + math.cos(math.pi / 6 + k * math.pi / 3) * R, cy + math.sin(math.pi / 6 + k * math.pi / 3) * R) for k in range(6)]
    d.polygon([(x + 18 * S, y + 24 * S) for x, y in hexa], fill=(0, 0, 0, 90))
    d.polygon(hexa, fill="#7a1fd0", outline="#e8d8ff")
    inner = [(cx + math.cos(-math.pi / 2 + k * 2 * math.pi / 3) * R * 0.62, cy + math.sin(-math.pi / 2 + k * 2 * math.pi / 3) * R * 0.62) for k in range(3)]
    d.polygon(inner, fill="#9a3ff0", outline="#e8d8ff")
    for k, pt in enumerate(hexa):
        d.line((*pt, *inner[((k + 1) // 2) % 3]), fill="#e8d8ff", width=3 * S)
    d.text((cx, cy + 20 * S), "20", font=render.font({}, "title", 150 * S), fill="#fff6d0", anchor="mm")
    return B._finish(im)


def draw_circuit() -> Image.Image:
    im, d = _new("#0d4a2a")
    rnd = random.Random(21)
    trace = "#c9b84a"
    for _ in range(46):                                                     # traces between pads
        x, y = rnd.randrange(60, W - 60) * S, rnd.randrange(60, H - 60) * S
        pts = [(x, y)]
        for _ in range(rnd.randrange(2, 5)):
            step = rnd.randrange(50, 180) * S
            dx, dy = rnd.choice([(1, 0), (0, 1), (1, 1), (-1, 1), (-1, 0), (0, -1)])
            x, y = max(50 * S, min((W - 50) * S, x + dx * step)), max(50 * S, min((H - 50) * S, y + dy * step))
            pts.append((x, y))
        d.line(pts, fill=trace, width=7 * S, joint="curve")
        for px, py in (pts[0], pts[-1]):
            B._disc(d, px, py, 13 * S, trace, "#0d4a2a", 4 * S)
    for cx, cy, w, h in ((260, 330, 170, 120), (520, 660, 150, 210), (230, 840, 200, 100)):       # chips
        d.rectangle(((cx - w // 2) * S, (cy - h // 2) * S, (cx + w // 2) * S, (cy + h // 2) * S), fill="#16161a", outline="#8a8a95", width=3 * S)
        for k in range(8):
            y0 = cy - h // 2 + 12 + k * (h - 24) // 8
            d.rectangle(((cx - w // 2 - 22) * S, y0 * S, (cx - w // 2) * S, (y0 + 8) * S), fill="#c0c0c8")
            d.rectangle(((cx + w // 2) * S, y0 * S, (cx + w // 2 + 22) * S, (y0 + 8) * S), fill="#c0c0c8")
        B._disc(d, (cx - w // 2 + 20) * S, (cy - h // 2 + 20) * S, 6 * S, "#8a8a95")
    B._frame(d, S, "#e6e6a0", 22, 7, 46)
    return B._finish(im)


DRAW = {"pizza": draw_pizza, "cat": draw_cat, "bat": draw_bat, "gears": draw_gears, "synth": draw_synth, "d20": draw_d20, "circuit": draw_circuit}
