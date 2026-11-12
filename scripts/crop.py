import sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from proxy_forge import config, render
arts = sorted((config.DATA / "art").glob("*.png"), key=lambda p: p.stat().st_mtime)
art = Image.open(arts[-1]).convert("RGB")
im = render.render(render.sample_unit(), art, render.get_template("classic"))
top = im.crop((20, 20, 740, 180)); bot = im.crop((20, 570, 740, 1050))
s = Image.new("RGB", (720, 640), "#222"); s.paste(top, (0, 0)); s.paste(bot, (0, 160)); s.save(sys.argv[1])
