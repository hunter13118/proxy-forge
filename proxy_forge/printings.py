"""
Every printing of every card, in one SQLite file on G: (`scryfall/printings.sqlite`).

scryfall.py keeps one row per card *name* (enough for AI art, where the printing does not matter). Set-locked art and price ranking need the printing: which set, which
collector number, which illustration and frame, what it costs. This index is built from Scryfall's `default_cards` bulk file (about 110k printings, ~500 MB), streamed
line by line (the file is gzipped JSON Lines) so it is never held in memory, written to a new file and swapped in only when complete. Every query afterwards is local.

Nothing here draws or downloads images; that is scans.py (M2). Tests run it on a small fixture through an injectable `httpx` transport.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

import httpx

from . import config, treatments
from .scryfall import API, HEADERS, SEPARATE_FACES, _norm

log = logging.getLogger("printings")
MAX_AGE_S = 7 * 86400
SKIP_LAYOUTS = {"art_series", "vanguard", "scheme", "planar"}      # tokens and emblems are kept (is_token), in their own name table
TOKEN_LAYOUTS = {"token", "double_faced_token", "emblem"}
SCHEMA_VERSION = "2"
SCHEMA = """
create table printings (
  id text primary key, oracle_id text not null, name_norm text not null,
  set_code text not null, cn text not null, cn_num integer,
  released_at text, lang text, illustration_id text, artist text, treatment text not null,
  border_color text, frame text, frame_effects text, promo_types text, finishes text,
  full_art int, textless int, digital int, oversized int, paper int,
  image_status text, faces int, is_token int default 0, usd real, usd_foil real, usd_etched real, eur real, eur_foil real,
  json text not null);
create index p_oracle on printings(oracle_id);
create index p_set_cn on printings(set_code, cn);
create index p_art on printings(illustration_id, treatment);
create table names (name_norm text, oracle_id text);
create index n_name on names(name_norm);
create table token_names (name_norm text, oracle_id text);
create table sets (code text primary key, name text, set_type text, released_at text, parent text, card_count int, icon_uri text, icon_svg text, digital int);
create table meta (k text primary key, v text);
"""


def _price(card: dict, key: str) -> float | None:
    try:
        return float((card.get("prices") or {}).get(key))
    except (TypeError, ValueError):
        return None


def _cn_num(cn: str) -> int:
    digits = ""
    for ch in cn:
        if not ch.isdigit():
            break
        digits += ch
    return int(digits) if digits else 0


def _oracle_id(card: dict) -> str:
    return card.get("oracle_id") or next((f["oracle_id"] for f in card.get("card_faces") or [] if f.get("oracle_id")), "") or card["id"]


def row(card: dict) -> tuple:
    faces = card.get("card_faces") or []
    return (card["id"], _oracle_id(card), _norm(card.get("name", "")), card.get("set", ""), str(card.get("collector_number", "")), _cn_num(str(card.get("collector_number", ""))),
            card.get("released_at"), card.get("lang", "en"), card.get("illustration_id") or next((f.get("illustration_id") for f in faces if f.get("illustration_id")), None),
            card.get("artist"), treatments.treatment(card), card.get("border_color"), card.get("frame"), json.dumps(card.get("frame_effects") or []),
            json.dumps(card.get("promo_types") or []), json.dumps(card.get("finishes") or []), int(bool(card.get("full_art"))), int(bool(card.get("textless"))),
            int(bool(card.get("digital"))), int(bool(card.get("oversized"))), int("paper" in (card.get("games") or [])), card.get("image_status"),
            len(faces) if faces and card.get("layout") in SEPARATE_FACES else 1, int(card.get("layout") in TOKEN_LAYOUTS), _price(card, "usd"), _price(card, "usd_foil"), _price(card, "usd_etched"),
            _price(card, "eur"), _price(card, "eur_foil"), json.dumps(card, ensure_ascii=False, separators=(",", ":")))


def _lines(path: Path):
    """The cards of a bulk file: gzipped or plain, JSON Lines or one JSON array."""
    with open(path, "rb") as f:
        gz = f.read(2) == b"\x1f\x8b"
    opener = gzip.open if gz else open
    with opener(path, "rt", encoding="utf-8") as f:
        first = f.readline()
        if first.lstrip().startswith("["):                                  # legacy one-array file: no streaming parser here, but the file is read once and dropped
            yield from json.loads(first + f.read())
            return
        for line in _chain(first, f):
            line = line.strip()
            if line:
                yield json.loads(line)


def _chain(first, rest):
    yield first
    yield from rest


class Printings:
    def __init__(self, path=None, transport: httpx.BaseTransport | None = None):
        self.path = Path(path) if path else config.folder("scryfall") / "printings.sqlite"
        self.transport = transport
        self._lock = threading.Lock()
        self._last = 0.0

    # ------------------------------------------------------------------------------------------------------------------------------------------------- building
    def _client(self, timeout: float = 120) -> httpx.Client:
        return httpx.Client(timeout=timeout, follow_redirects=True, transport=self.transport)

    def _get(self, c: httpx.Client, url: str, **kw) -> httpx.Response:
        with self._lock:                                                    # 100 ms between API calls, as Scryfall asks
            wait = 0.1 - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
        return c.get(url, headers=HEADERS, **kw)

    def ready(self) -> bool:
        """Built, and by this version of the code (an older file lacks the token tables: it is rebuilt)."""
        try:
            with self._db() as db:
                r = db.execute("select v from meta where k='schema'").fetchone()
        except sqlite3.Error:
            return False
        return bool(r) and r[0] == SCHEMA_VERSION and self.age() is not None

    def age(self) -> float | None:
        try:
            with self._db() as db:
                r = db.execute("select v from meta where k='built_at'").fetchone()
        except sqlite3.Error:
            return None
        return time.time() - float(r[0]) if r else None

    def stale(self, max_age: float = MAX_AGE_S) -> bool:
        a = self.age()
        return a is None or a > max_age

    def build(self, progress=lambda msg: None, source: Path | None = None) -> int:
        """Download `default_cards` (or read `source`, a local bulk file) and rebuild the index. The old file stays in use until the new one is complete. Returns the printings kept."""
        part = self.path.with_suffix(".bulk.part")
        new = self.path.with_suffix(".sqlite.new")
        new.unlink(missing_ok=True)
        with self._client() as c:
            if source is None:
                info = next(b for b in self._get(c, f"{API}/bulk-data").json()["data"] if b["type"] == "default_cards")
                url = info.get("jsonl_download_uri") or info["download_uri"]
                progress(f"downloading Scryfall printings ({(info.get('compressed_size') or info.get('size') or 0) // 1_000_000} MB)")
                with c.stream("GET", url, headers=HEADERS) as r:
                    r.raise_for_status()
                    with open(part, "wb") as f:
                        for chunk in r.iter_bytes(1 << 20):
                            f.write(chunk)
                source = part
            progress("downloading the set list")
            sets = self._get(c, f"{API}/sets").json().get("data", [])
        db = sqlite3.connect(new)
        try:
            db.executescript(SCHEMA)
            kept, batch, names, tnames = 0, [], [], []
            ins = "insert or replace into printings values (" + ",".join("?" * 30) + ")"
            for card in _lines(source):
                if card.get("layout") in SKIP_LAYOUTS or card.get("object") == "token" or not card.get("id"):
                    continue
                batch.append(row(card))
                oid = batch[-1][1]
                is_tok = card.get("layout") in TOKEN_LAYOUTS
                for n in {_norm(card.get("name", "")), *(_norm(f.get("name", "")) for f in card.get("card_faces") or [])} - {""}:
                    (tnames if is_tok else names).append((n, oid))
                kept += 1
                if len(batch) >= 5000:
                    db.executemany(ins, batch)
                    db.executemany("insert into names values (?, ?)", names)
                    db.executemany("insert into token_names values (?, ?)", tnames)
                    db.commit()
                    batch, names, tnames = [], [], []
                    progress(f"indexing printings ({kept})")
            db.executemany(ins, batch)
            db.executemany("insert into names values (?, ?)", names)
            db.executemany("insert into token_names values (?, ?)", tnames)
            db.execute("create table tu as select distinct name_norm, oracle_id from token_names")
            db.execute("drop table token_names")
            db.execute("alter table tu rename to token_names")
            db.execute("create index tn_name on token_names(name_norm)")
            db.execute("create table nu as select distinct name_norm, oracle_id from names")                 # one row per (name, card)
            db.execute("drop table names")
            db.execute("alter table nu rename to names")
            db.execute("create index n_name on names(name_norm)")
            db.executemany("insert or replace into sets values (?,?,?,?,?,?,?,?,?)",
                           [(s["code"], s.get("name"), s.get("set_type"), s.get("released_at"), s.get("parent_set_code"), s.get("card_count"), s.get("icon_svg_uri"), None,
                             int(bool(s.get("digital")))) for s in sets])
            db.execute("insert into meta values ('built_at', ?)", (str(time.time()),))
            db.execute("insert into meta values ('count', ?)", (str(kept),))
            db.execute("insert into meta values ('schema', ?)", (SCHEMA_VERSION,))
            db.commit()
        finally:
            db.close()
        part.unlink(missing_ok=True)
        os.replace(new, self.path)                                          # atomic: readers see the old index or the new one, never half
        log.info("printings index: %d printings, %d sets", kept, len(sets))
        return kept

    # ------------------------------------------------------------------------------------------------------------------------------------------------- queries
    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def tokens_named(self, name: str) -> list[dict]:
        """Every printing of every token called `name` (a face name works), newest first. Several different tokens share a name (Insect, Soldier ...): they differ in oracle id."""
        with self._db() as db:
            q = "select * from printings where is_token=1 and oracle_id in (select oracle_id from token_names where name_norm=?) order by released_at desc, set_code, cn_num"
            return [dict(r) for r in db.execute(q, (_norm(name),))]

    def token_card(self, name: str, set_code: str = "", number: str = "", prefer_sets: list[str] | None = None) -> dict | None:
        """The Scryfall card (as a dict) a deck-list token line means. A stated set and number win; then the sets in `prefer_sets`; then the commonest token of that name (the one with the
        most printings), in its newest good scan. None when no token has that name."""
        if set_code and number:
            p = self.by_set_cn(set_code, number)
            if p and p["is_token"]:
                return json.loads(p["json"])
        cands = self.tokens_named(name)
        if not cands:
            return None
        if set_code:
            inset = [p for p in cands if p["set_code"] == set_code.lower()]
            cands = inset or cands
        elif prefer_sets:
            fam = self.family([c.lower() for c in prefer_sets])
            inset = [p for p in cands if p["set_code"] in fam]
            cands = inset or cands
        by_oracle: dict[str, list[dict]] = {}
        for p in cands:
            by_oracle.setdefault(p["oracle_id"], []).append(p)
        best = max(by_oracle.values(), key=len)
        rank = {"highres_scan": 3, "lowres": 2, "placeholder": 0, "missing": 0}
        best.sort(key=lambda p: (rank.get(p["image_status"], 0), p["released_at"] or ""), reverse=True)
        return json.loads(best[0]["json"])

    def token_variants(self, name: str) -> list[dict]:
        """Like `variants`, over every token called `name` (they are different tokens, one per oracle id), grouped by illustration and look."""
        rank = {"highres_scan": 3, "lowres": 2, "placeholder": 1, "missing": 0}
        groups: dict[tuple, list[dict]] = {}
        for p in self.tokens_named(name):
            groups.setdefault((p["illustration_id"] or p["id"], p["treatment"], p["oracle_id"]), []).append(p)
        out = []
        for (ill, t, oid), ps in groups.items():
            ps.sort(key=lambda p: (rank.get(p["image_status"], 0), p["released_at"] or ""), reverse=True)
            out.append({"illustration_id": ill, "treatment": t, "oracle_id": oid, "best": ps[0], "printings": ps})
        out.sort(key=lambda v: v["best"]["released_at"] or "", reverse=True)
        return out

    def count(self) -> int:
        with self._db() as db:
            return db.execute("select count(*) from printings").fetchone()[0]

    def oracle_ids(self, names: list[str]) -> dict[str, str | None]:
        """Deck-list names -> oracle ids (a face name works; None when unknown)."""
        out: dict[str, str | None] = {}
        with self._db() as db:
            for n in names:
                r = db.execute("select oracle_id from names where name_norm=? limit 1", (_norm(n),)).fetchone()
                out[n] = r[0] if r else None
        return out

    def for_oracle(self, oid: str, paper_only: bool = True) -> list[dict]:
        """Every printing of a card, newest first. Digital, oversized and non-paper printings are left out unless `paper_only` is false."""
        q = "select * from printings where oracle_id=?" + (" and paper=1 and digital=0 and oversized=0" if paper_only else "") + " order by released_at desc, set_code, cn_num, cn"
        with self._db() as db:
            return [dict(r) for r in db.execute(q, (oid,))]

    def family(self, codes: list[str]) -> list[str]:
        """The sets and their children (promos, Commander decks, bonus sheets: `parent_set_code`), in the order given, parents first."""
        out: list[str] = []
        with self._db() as db:
            for c in codes:
                for x in [c, *[r[0] for r in db.execute("select code from sets where parent=? order by released_at", (c,))]]:
                    if x not in out:
                        out.append(x)
        return out

    def in_sets(self, oid: str, codes: list[str], family: bool = True) -> list[dict]:
        """Printings of a card inside the given sets (and their families), in chain order: all of the first set's, then the second's ... Within a set: collector-number order."""
        order = self.family(codes) if family else list(codes)
        mine: dict[str, list[dict]] = {}
        for p in self.for_oracle(oid):
            mine.setdefault(p["set_code"], []).append(p)
        return [p for c in order for p in sorted(mine.get(c, []), key=lambda p: (p["cn_num"], p["cn"]))]

    def by_set_cn(self, set_code: str, cn: str) -> dict | None:
        with self._db() as db:
            r = db.execute("select * from printings where set_code=? and cn=? limit 1", (set_code.lower(), str(cn))).fetchone()
        return dict(r) if r else None

    def coverage(self, oids: list[str]) -> dict[str, int]:
        """For every set: how many of these cards (distinct oracle ids) have a paper printing in it. One GROUP BY."""
        oids = list(dict.fromkeys(oids))
        out: dict[str, int] = {}
        with self._db() as db:
            for i in range(0, len(oids), 500):
                chunk = oids[i:i + 500]
                q = f"select set_code, oracle_id from printings where oracle_id in ({','.join('?' * len(chunk))}) and paper=1 and digital=0 and oversized=0"
                seen = {(r[0], r[1]) for r in db.execute(q, chunk)}
                for s, _ in seen:
                    out[s] = out.get(s, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

    def sets(self, q: str = "", set_type: str = "") -> list[dict]:
        where, args = ["digital=0"], []
        if q:
            where.append("(code like ? or name like ?)")
            args += [f"%{q}%", f"%{q}%"]
        if set_type:
            where.append("set_type=?")
            args.append(set_type)
        with self._db() as db:
            return [dict(r) for r in db.execute(f"select * from sets where {' and '.join(where)} order by released_at desc", args)]

    def variants(self, oid: str, look_promos: bool = False) -> list[dict]:
        """The art variants of a card: printings grouped by (illustration, treatment). Each variant: its best printing (highest image status, then newest) and all printings."""
        rank = {"highres_scan": 3, "lowres": 2, "placeholder": 1, "missing": 0}
        groups: dict[tuple, list[dict]] = {}
        for p in self.for_oracle(oid):
            t = treatments.treatment(json.loads(p["json"]), look_promos) if look_promos else p["treatment"]
            groups.setdefault((p["illustration_id"] or p["id"], t), []).append(p)
        out = []
        for (ill, t), ps in groups.items():
            ps.sort(key=lambda p: (rank.get(p["image_status"], 0), p["released_at"] or ""), reverse=True)
            out.append({"illustration_id": ill, "treatment": t, "best": ps[0], "printings": ps})
        out.sort(key=lambda v: v["best"]["released_at"] or "", reverse=True)
        return out
