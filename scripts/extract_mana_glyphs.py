"""Reads fonts/mana.css (from the mana-font package) and writes fonts/mana-glyphs.json: symbol name -> the character in mana.ttf."""
import json
import re
from pathlib import Path

fonts = Path(__file__).resolve().parent.parent / "fonts"
css = (fonts / "mana.css").read_text(encoding="utf-8")
glyphs = {}
for rule in css.split("}"):
    sel, _, body = rule.partition("{")
    c = re.search(r'content:\s*"\\([0-9a-fA-F]+)"', body)
    if not c or "before" not in sel:
        continue
    for name in re.findall(r"\.ms-([a-z0-9\-]+)::?before", sel):
        glyphs.setdefault(name, c.group(1))
(fonts / "mana-glyphs.json").write_text(json.dumps(glyphs, indent=0), encoding="utf-8")
print(len(glyphs), {k: glyphs.get(k) for k in ["w", "u", "b", "r", "g", "c", "s", "x", "0", "1", "2", "tap", "untap", "e", "wu", "wb", "2w", "wp", "wup", "q"]})
