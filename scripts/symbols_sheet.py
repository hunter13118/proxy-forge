"""A contact sheet of the symbols and the three templates, for looking at: python scripts/symbols_sheet.py out.png"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from proxy_forge import render  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "symbols.png"
tpl = render.get_template("classic")
syms = ["W", "U", "B", "R", "G", "C", "S", "X", "0", "1", "2", "3", "7", "10", "T", "Q", "E", "W/U", "U/B", "B/R", "R/G", "G/W", "W/B", "U/R", "B/G", "R/W", "G/U", "2/W", "2/U", "2/B", "2/R", "2/G", "W/P", "U/P", "B/P", "R/P", "G/P", "C/W"]
dia = 64
cols = 10
sheet = Image.new("RGB", (cols * (dia + 14) + 14, ((len(syms) + cols - 1) // cols) * (dia + 14) + 14 + 330), "#d8cfae")
for i, s in enumerate(syms):
    render.pip(sheet, tpl, s, 14 + (i % cols) * (dia + 14), 14 + (i // cols) * (dia + 14), dia, shadow=True)
card = render.render(render.sample_unit(), None, tpl, scale=0.3)
y = 14 + ((len(syms) + cols - 1) // cols) * (dia + 14)
for j, t in enumerate(("classic", "fullart", "noir")):
    sheet.paste(render.render(render.sample_unit(), None, render.get_template(t), scale=0.3), (14 + j * 240, y))
sheet.save(out)
print(sheet.size)
