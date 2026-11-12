"""Reading a deck list: the plain-text export every deck site offers ("4 Lightning Bolt", "4x Lightning Bolt (M10) 146", "SB: 2 Negate", section headings)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_LINE = re.compile(r"^(?:(?P<sb>SB:)\s*)?(?:(?P<qty>\d+)\s*x?\s+)?(?P<name>.+?)\s*(?:\((?P<set>[A-Za-z0-9]{2,6})\)\s*(?P<num>[\w\-★]+)?)?\s*(?:\*[A-Za-z]+\*)?\s*$")
_SECTIONS = {"deck": "main", "main": "main", "mainboard": "main", "maindeck": "main", "commander": "commander", "commanders": "commander", "companion": "sideboard",
             "sideboard": "sideboard", "side": "sideboard", "maybeboard": "maybe", "considering": "maybe", "tokens": "tokens"}


@dataclass
class Entry:
    qty: int
    name: str
    section: str = "main"
    set: str = ""
    number: str = ""


def parse(text: str) -> list[Entry]:
    """Every card line in the list, merged by (name, section). Blank lines, // comments and headings are not cards; a blank line after a sideboard heading stays in it."""
    out: dict[tuple[str, str], Entry] = {}
    section = "main"
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith(("//", "#")):
            continue
        head = line.rstrip(":").strip().lower()
        if head in _SECTIONS and not line[0].isdigit():
            section = _SECTIONS[head]
            continue
        m = _LINE.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        if not name or name.lower() in _SECTIONS:
            continue
        sec = "sideboard" if m.group("sb") else section
        qty = int(m.group("qty") or 1)
        key = (name.lower(), sec)
        if key in out:
            out[key].qty += qty
        else:
            out[key] = Entry(qty=qty, name=name, section=sec, set=(m.group("set") or "").lower(), number=m.group("num") or "")
    return list(out.values())
