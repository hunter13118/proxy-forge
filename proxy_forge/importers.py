"""
Deck intake beyond pasted text: files (.txt, MTGA exports, MTGO .dek XML, .csv from Moxfield / Deckbox / Archidekt) and Archidekt links. Everything becomes the plain list deck.py reads
(`4 Lightning Bolt (M10) 146`, with `Commander` / `Sideboard` headings), so the rest of the app has one input format.

Archidekt's API is public but unofficial and can change; if it does, the answer says so and "paste the text export" still works. Moxfield has no public API: use its text export.
"""
from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET

import httpx

from .scryfall import HEADERS


class ImportError_(ValueError):
    pass


def _line(qty, name, set_="", num="") -> str:
    return f"{qty} {name}" + (f" ({set_.upper()}) {num}" if set_ and num else "")


def from_dek(raw: bytes) -> str:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ImportError_(f"not a valid .dek file: {e}")
    main, side = [], []
    for c in root.iter("Cards"):
        name = c.get("Name")
        if name:
            (side if (c.get("Sideboard") or "").lower() == "true" else main).append(_line(int(c.get("Quantity") or 1), name))
    return "\n".join(main + (["", "Sideboard"] + side if side else []))


def from_csv(raw: bytes) -> str:
    text = raw.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ImportError_("the CSV has no rows")
    keys = {k.lower().strip(): k for k in rows[0]}
    qk = next((keys[k] for k in ("count", "quantity", "qty", "amount") if k in keys), None)
    nk = next((keys[k] for k in ("name", "card name", "card") if k in keys), None)
    if not nk:
        raise ImportError_("the CSV needs a Name column")
    sk = next((keys[k] for k in ("edition", "set", "set code", "setcode", "expansion") if k in keys), None)
    ck = next((keys[k] for k in ("collector number", "collector_number", "card number", "number") if k in keys), None)
    bk = next((keys[k] for k in ("board", "section", "category", "categories") if k in keys), None)
    main, side, cmd = [], [], []
    for r in rows:
        name = (r.get(nk) or "").strip()
        if not name:
            continue
        qty = int(float(r.get(qk) or 1)) if qk else 1
        board = (r.get(bk) or "").lower() if bk else ""
        s = (r.get(sk) or "").strip() if sk else ""
        line = _line(qty, name, s if re.fullmatch(r"[A-Za-z0-9]{2,6}", s or "") else "", (r.get(ck) or "").strip() if ck else "")
        (cmd if "commander" in board else side if "side" in board else main).append(line)
    return "\n".join((["Commander"] + cmd + ["", "Deck"] if cmd else []) + main + (["", "Sideboard"] + side if side else []))


def from_file(name: str, raw: bytes) -> tuple[str, list[str]]:
    """(deck list text, warnings) for an uploaded file."""
    low = name.lower()
    if low.endswith(".dek") or raw.lstrip()[:5] == b"<?xml" or raw.lstrip()[:5] == b"<Deck":
        return from_dek(raw), []
    if low.endswith(".csv"):
        return from_csv(raw), []
    text = raw.decode("utf-8-sig", errors="replace")
    return text, (["MTG Arena exports are read as they are; an Arena-only set code that Scryfall does not know is ignored and the card follows your set chain."] if re.search(r"\([A-Z0-9]{2,6}\) \d+", text) else [])


def from_archidekt(url: str, transport: httpx.BaseTransport | None = None) -> tuple[str, list[str]]:
    m = re.search(r"archidekt\.com/(?:decks|api/decks)/(\d+)", url)
    if not m:
        raise ImportError_("that is not an Archidekt deck link (https://archidekt.com/decks/123456/...). Moxfield has no public API: paste its text export instead.")
    with httpx.Client(timeout=30, follow_redirects=True, transport=transport) as c:
        r = c.get(f"https://archidekt.com/api/decks/{m.group(1)}/", headers={"User-Agent": HEADERS["User-Agent"], "Accept": "application/json"})
    if r.status_code != 200:
        raise ImportError_(f"Archidekt answered {r.status_code}. The deck may be private, or Archidekt's unofficial API changed: paste the text export instead.")
    try:
        cards = r.json()["cards"]
    except Exception:
        raise ImportError_("Archidekt's answer was not what was expected (its API is unofficial). Paste the text export instead.")
    main, side, cmd, skipped = [], [], [], 0
    for e in cards:
        cats = [x.lower() for x in e.get("categories") or []]
        c = e.get("card") or {}
        name = (c.get("oracleCard") or {}).get("name") or c.get("name")
        if not name:
            continue
        if "maybeboard" in cats or "considering" in cats:
            skipped += 1
            continue
        line = _line(e.get("quantity", 1), name, (c.get("edition") or {}).get("editioncode", ""), c.get("collectorNumber", ""))
        (cmd if "commander" in cats else side if "sideboard" in cats else main).append(line)
    return "\n".join((["Commander"] + cmd + ["", "Deck"] if cmd else []) + main + (["", "Sideboard"] + side if side else [])), ([f"{skipped} maybeboard cards were left out."] if skipped else [])
