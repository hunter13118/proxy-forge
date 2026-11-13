"""Reading a deck list: the plain-text export every deck site offers ("4 Lightning Bolt", "4x Lightning Bolt (M10) 146", "SB: 2 Negate", section headings)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_LINE = re.compile(r"^(?:(?P<sb>SB:)\s*)?(?:(?P<qty>\d+)\s*x?\s+)?(?P<name>.+?)\s*(?:\((?P<set>[A-Za-z0-9]{2,6})\)\s*(?P<num>[\w\-★]+)?)?\s*(?:\*[A-Za-z]+\*)?\s*$")
_TAG = re.compile(r"\s*\[([A-Za-z][^\]]*)\]\s*$")
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
        tag = _TAG.search(line)                                                  # Archidekt's text export ends a line with its category: `[Creature]`, `[Commander{top}]`
        if tag:
            line = line[:tag.start()].rstrip()
        m = _LINE.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        if not name or name.lower() in _SECTIONS:
            continue
        sec = "sideboard" if m.group("sb") else section
        if tag and tag.group(1).lower().startswith("commander"):
            sec = "commander"
        elif tag and tag.group(1).lower().startswith(("sideboard", "maybeboard")):
            sec = "sideboard" if tag.group(1).lower().startswith("side") else "maybe"
        qty = int(m.group("qty") or 1)
        set_, num = (m.group("set") or "").lower(), m.group("num") or ""
        key = (name.lower(), sec, set_, num)                                      # the same card from different printings stays separate: `10x Swamp (40k) 310` and `10x Swamp (40k) 312`
        if key in out:
            out[key].qty += qty
        else:
            out[key] = Entry(qty=qty, name=name, section=sec, set=set_, number=num)
    return list(out.values())
