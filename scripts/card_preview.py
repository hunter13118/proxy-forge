"""Render one sample card per template with real art from the art cache, side by side: python scripts/card_preview.py out.png [scale]"""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from proxy_forge import config, render  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "cards.png"
scale = float(sys.argv[2]) if len(sys.argv) > 2 else 0.8
arts = sorted((config.DATA / "art").glob("*.png"), key=lambda p: p.stat().st_mtime)
art = Image.open(arts[-1]).convert("RGB") if arts else None
units = [render.sample_unit(),
         {"key": "b", "name": "Sheoldred, the Apocalypse", "mana_cost": "{2}{B}{B}", "type_line": "Legendary Creature — Phyrexian Praetor", "colors": ["B"],
          "oracle_text": "Deathtouch\nWhenever you draw a card, you gain 2 life.\nWhenever an opponent draws a card, they lose 2 life.", "power": "4", "toughness": "5"}]
ims = []
for u in units:
    ims.append(render.render(u, art, render.get_template("classic"), scale=scale))
for t in ("fullart", "noir"):
    ims.append(render.render(units[0], art, render.get_template(t), scale=scale))
w, h = ims[0].size
sheet = Image.new("RGB", (len(ims) * (w + 10) + 10, h + 20), "#2a2a2a")
for i, im in enumerate(ims):
    sheet.paste(im, (10 + i * (w + 10), 10))
sheet.save(out)
print(sheet.size)
