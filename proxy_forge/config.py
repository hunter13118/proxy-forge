"""Where things live and which models to use. Everything is overridable by environment; nothing is ever put on C:."""
from __future__ import annotations

import os
from pathlib import Path

DATA = Path(os.environ.get("PROXY_FORGE_DATA", r"G:\proxy-forge-data"))      # NVMe: Scryfall data, profiles, photos, art, decks
# The studio (ebook-av-service) does the models' work: words, pictures and LoRAs (studio.py). Loopback needs no token; through a tunnel it takes STUDIO_TOKEN.
STUDIO_URL = os.environ.get("STUDIO_URL", "http://127.0.0.1:7860")
STUDIO_TOKEN = os.environ.get("STUDIO_TOKEN", "")

# What goes into the prompts is proxy-forge's: quality words first (Anima's order). The model, steps and CFG are the studio's picture model's own (GET /v1/ai).
QUALITY = "masterpiece, best quality"
NEGATIVE = ("worst quality, low quality, blurry, jpeg artifacts, artist name, watermark, text, signature, speech bubble, comic, multiple views, split screen, panels, border, "
            "frame, card frame, trading card, 2koma, 4koma, chibi, white background, white border, white margins, letterboxed, borders, empty space, framed picture")
# Picture sizes Anima draws well, by the shape of the window a template asks for.
SIZES = {"landscape": (1216, 832), "portrait": (832, 1216), "square": (1024, 1024)}

# What keeps a drawing a cartoon when a person's LoRA (trained on photos) pulls it toward a photograph: these words, plus a second pass through the plain model (engine.graph_params).
CARTOON_TAGS = "cartoon, anime style, cel shading, flat color, bold lineart, vibrant colors, stylized"
CARTOON_STRENGTH = 0.4

SCRYFALL_UA = "proxy-forge/0.1 (personal playtest proxies; https://github.com/hunter13118)"


def folder(*parts: str) -> Path:
    p = DATA.joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p
