"""
Card data from Scryfall.

For a deck we never hit the per-card API in a loop: Scryfall's bulk `oracle_cards` file (one entry per card name, ~150 MB) is downloaded once, indexed into a small SQLite
file on G:, and looked up locally. The art is generated, so which printing a card is does not matter and oracle_cards is enough. A name that is not in the index (a new card,
a typo) goes to /cards/named?fuzzy= once, politely (a User-Agent, an Accept header, 100 ms apart), and the answer is kept.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

import httpx

from . import config

log = logging.getLogger("scryfall")
API = "https://api.scryfall.com"
HEADERS = {"User-Agent": config.SCRYFALL_UA, "Accept": "application/json;q=0.9,*/*;q=0.8"}
MAX_AGE_S = 14 * 86400
SEPARATE_FACES = {"transform", "modal_dfc", "double_faced_token", "reversible_card"}      # each face is its own card side, with its own art


def _norm(name: str) -> str:
    return " ".join(name.lower().replace("’", "'").split())


def units(card: dict) -> list[dict]:
    """The things to draw for a Scryfall card: one unit per card side. Split, adventure and flip cards are one unit with both halves in the text."""
    faces = card.get("card_faces") or []
    base = {"oracle_id": card.get("oracle_id") or card.get("id"), "layout": card.get("layout", "normal"), "set": card.get("set", ""), "color_identity": card.get("color_identity", [])}
    if faces and card.get("layout") in SEPARATE_FACES:
        return [{**base, "key": f"{base['oracle_id']}-{i}", "face": i, "faces": len(faces), "name": f.get("name", ""), "mana_cost": f.get("mana_cost", ""),
                 "type_line": f.get("type_line", ""), "oracle_text": f.get("oracle_text", ""), "flavor_text": f.get("flavor_text") or card.get("flavor_text", ""),
                 "power": f.get("power"), "toughness": f.get("toughness"), "loyalty": f.get("loyalty"), "defense": f.get("defense"), "colors": f.get("colors") or card.get("colors") or []}
                for i, f in enumerate(faces)]
    if faces:                                                                                                    # split / adventure / flip / aftermath
        f0 = faces[0]
        text = "\n".join(([f0.get("oracle_text", "")] + [f"{f.get('name', '')} {f.get('mana_cost', '')}\n{f.get('type_line', '')}\n{f.get('oracle_text', '')}".strip() for f in faces[1:]]))
        return [{**base, "key": f"{base['oracle_id']}-0", "face": 0, "faces": 1, "name": card.get("name", f0.get("name", "")), "mana_cost": f0.get("mana_cost", ""),
                 "type_line": f0.get("type_line", ""), "oracle_text": text, "flavor_text": f0.get("flavor_text") or "", "power": f0.get("power"), "toughness": f0.get("toughness"),
                 "loyalty": f0.get("loyalty"), "defense": f0.get("defense"), "colors": card.get("colors") or f0.get("colors") or []}]
    return [{**base, "key": f"{base['oracle_id']}-0", "face": 0, "faces": 1, "name": card.get("name", ""), "mana_cost": card.get("mana_cost", ""), "type_line": card.get("type_line", ""),
             "oracle_text": card.get("oracle_text", ""), "flavor_text": card.get("flavor_text", ""), "power": card.get("power"), "toughness": card.get("toughness"),
             "loyalty": card.get("loyalty"), "defense": card.get("defense"), "colors": card.get("colors") or []}]


class Scryfall:
    def __init__(self, path=None):
        self.path = path or (config.folder("scryfall") / "cards.sqlite")
        self._lock = threading.Lock()
        self._last = 0.0
        with self._db() as db:
            db.execute("create table if not exists cards (name text primary key, json text not null)")        # name: normalised full name, and each face name too
            db.execute("create table if not exists meta (k text primary key, v text)")

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _get(self, client: httpx.Client, url: str, **kw) -> httpx.Response:
        with self._lock:                                                    # 100 ms between calls, as Scryfall asks
            wait = 0.1 - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
        return client.get(url, headers=HEADERS, **kw)

    def age(self) -> float | None:
        with self._db() as db:
            row = db.execute("select v from meta where k='bulk_at'").fetchone()
        return time.time() - float(row[0]) if row else None

    def count(self) -> int:
        with self._db() as db:
            return db.execute("select count(*) from cards").fetchone()[0]

    def refresh_bulk(self, force: bool = False, progress=lambda msg: None) -> int:
        """Download oracle_cards and index it. Skipped when the index is under two weeks old (unless `force`)."""
        age = self.age()
        if not force and age is not None and age < MAX_AGE_S:
            return self.count()
        with httpx.Client(timeout=120, follow_redirects=True) as c:
            info = next(b for b in self._get(c, f"{API}/bulk-data").json()["data"] if b["type"] == "oracle_cards")
            progress(f"downloading Scryfall oracle cards ({info.get('size', 0) // 1_000_000} MB)")
            tmp = self.path.with_suffix(".json.part")
            with c.stream("GET", info["download_uri"], headers=HEADERS) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
        progress("indexing")
        cards = json.loads(tmp.read_text(encoding="utf-8"))
        tmp.unlink(missing_ok=True)
        rows = {}
        for card in cards:
            if card.get("layout") in ("token", "emblem", "art_series", "vanguard", "scheme", "planar") or card.get("set_type") in ("token", "memorabilia"):
                continue
            blob = json.dumps(card, ensure_ascii=False)
            rows[_norm(card["name"])] = blob
            for f in card.get("card_faces") or []:
                rows.setdefault(_norm(f.get("name", "")), blob)
        with self._db() as db:
            db.execute("delete from cards")
            db.executemany("insert or replace into cards values (?, ?)", rows.items())
            db.execute("insert or replace into meta values ('bulk_at', ?)", (str(time.time()),))
        log.info("indexed %d names from %d cards", len(rows), len(cards))
        return len(rows)

    def lookup(self, name: str) -> dict | None:
        """The Scryfall card for a deck-list name: from the index, else one fuzzy call (kept). None when Scryfall does not know it."""
        n = _norm(name)
        with self._db() as db:
            row = db.execute("select json from cards where name=?", (n,)).fetchone()
        if row:
            return json.loads(row[0])
        try:
            with httpx.Client(timeout=30) as c:
                r = self._get(c, f"{API}/cards/named", params={"fuzzy": name})
            if r.status_code != 200:
                return None
            card = r.json()
        except Exception as e:
            log.warning("scryfall fuzzy lookup of %r failed: %s", name, e)
            return None
        blob = json.dumps(card, ensure_ascii=False)
        with self._db() as db:
            db.execute("insert or replace into cards values (?, ?)", (_norm(card["name"]), blob))
            db.execute("insert or replace into cards values (?, ?)", (n, blob))
        return card
