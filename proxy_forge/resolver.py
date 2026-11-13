"""
Which printing does each card of a deck use? (Archive: set-locked art; Vault: priciest variant, see vault.py.)

Pure local queries against the printings index: no network. The match is exact on Scryfall's set code and collector number; a card that is not in the chosen set is never
silently given "another printing with the same name": it takes the fallback rule the owner chose and is marked `fallback` with the reason, so the page can show it in amber.

A resolution is a dict: {"printing": {...}, "why": "chain:mh3", "fallback": False, "pin_missing": False} or {"forge": True, "why": ...} (draw it with AI) or {"blank": True, ...}.
"""
from __future__ import annotations

import json
from datetime import date

from .printings import Printings

DEFAULT_POLICY = {"source": "forge", "sets": [], "family": True, "treatment": "regular", "pins": True, "fallback": "nearest", "vary_basics": True,
                  "vault": {"currency": "usd", "basis": "median", "foil": True, "serialized": False, "guard": True}, "print": "scan"}
STATUS_RANK = {"highres_scan": 3, "lowres": 2, "placeholder": 0, "missing": 0}
SEPARATE = {"transform", "modal_dfc", "double_faced_token", "reversible_card"}
BASICS = {"plains", "island", "swamp", "mountain", "forest", "wastes"}


def policy_of(deck: dict) -> dict:
    p = {**DEFAULT_POLICY, **(deck.get("art_policy") or {})}
    p["vault"] = {**DEFAULT_POLICY["vault"], **p.get("vault", {})}
    return p


def is_basic(unit: dict) -> bool:
    t = unit.get("type_line", "")
    return t.startswith("Basic") and "Land" in t


def usable(p: dict) -> bool:
    return p["image_status"] not in ("placeholder", "missing")


def _pref_rank(p: dict, pref: str) -> int:
    t = p["treatment"]
    if pref == "any":
        return 0
    if pref == "regular":
        return 0 if t.startswith("regular") else 1
    return 0 if pref in t.replace("extended", "extended").split("-") else 1


def pick_in_set(cands: list[dict], pref: str) -> dict | None:
    """The best printing among those of one set: treatment preference, then scan quality, then collector number."""
    ok = [p for p in cands if usable(p)]
    if not ok:
        return None
    return sorted(ok, key=lambda p: (_pref_rank(p, pref), -STATUS_RANK.get(p["image_status"], 0), p["cn_num"], p["cn"]))[0]


def brief(p: dict, pr: Printings | None = None) -> dict:
    from . import treatments
    card = json.loads(p["json"]) if p.get("json") else {}
    return {"id": p["id"], "set": p["set_code"], "cn": p["cn"], "treatment": p["treatment"], "label": treatments.label(card) if card else p["treatment"], "artist": p["artist"],
            "image_status": p["image_status"], "released": p["released_at"], "name": card.get("name", "")}


def oracle_of(pr: Printings, unit: dict) -> str | None:
    oid = unit.get("oracle_id")
    if oid and pr.for_oracle(oid):
        return oid
    return pr.oracle_ids([unit.get("name", "")]).get(unit.get("name", ""))


def _days(a: str | None, b: str | None) -> int:
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except (TypeError, ValueError):
        return 10 ** 6


def _nearest(pr: Printings, oid: str, anchor_set: str, pref: str) -> tuple[dict | None, str]:
    allp = [p for p in pr.for_oracle(oid) if usable(p)]
    if not allp:
        return None, ""
    srel = next((s["released_at"] for s in pr.sets() if s["code"] == anchor_set), None)
    best_set = min({p["set_code"] for p in allp}, key=lambda c: min(_days(p["released_at"], srel) for p in allp if p["set_code"] == c))
    p = pick_in_set([x for x in allp if x["set_code"] == best_set], pref)
    return p, f"nearest to {anchor_set.upper()}"


def _default(pr: Printings, oid: str) -> dict | None:
    """Scryfall's own default printing is not in the bulk file; this is the newest regular, best-scanned paper printing."""
    allp = [p for p in pr.for_oracle(oid) if usable(p)]
    reg = [p for p in allp if p["treatment"].startswith("regular")] or allp
    return sorted(reg, key=lambda p: (-STATUS_RANK.get(p["image_status"], 0), _neg(p["released_at"])))[0] if reg else None


def _neg(s):
    return tuple(-ord(c) for c in (s or ""))


def resolve_unit(pr: Printings, unit: dict, policy: dict) -> dict:
    """The Archive rule for one card."""
    oid = oracle_of(pr, unit)
    if oid is None:
        return {"forge": True, "why": "card not in the printings index", "fallback": True}
    chain = [c.lower() for c in policy.get("sets", [])]
    pref = policy.get("treatment", "regular")
    pin = unit.get("pin") or {}
    pin_missing = False
    if policy.get("pins", True) and pin.get("set"):
        p = pr.by_set_cn(pin["set"], pin.get("number", "")) if pin.get("number") else None
        if p is None and pin.get("set"):                                           # a set without a number: the best printing in that set
            p = pick_in_set(pr.in_sets(oid, [pin["set"]], family=False), pref)
        if p and p["oracle_id"] == oid and usable(p):
            return {"printing": p, "why": f"pinned {pin['set'].upper()} {pin.get('number', '')}".strip(), "fallback": False, "pin_missing": False}
        pin_missing = True
    for code in (pr.family(chain) if policy.get("family", True) else chain):
        p = pick_in_set([x for x in pr.in_sets(oid, [code], family=False)], pref)
        if p:
            return {"printing": p, "why": f"chain:{code}", "fallback": False, "pin_missing": pin_missing}
    mode = policy.get("fallback", "nearest")
    where = "/".join(c.upper() for c in chain) or "the chosen sets"
    if mode == "forge":
        return {"forge": True, "why": f"not printed in {where}; AI art", "fallback": True, "pin_missing": pin_missing}
    if mode == "blank":
        return {"blank": True, "why": f"not printed in {where}", "fallback": True, "pin_missing": pin_missing}
    if mode == "default":
        p, how = _default(pr, oid), "default printing"
    else:
        p, how = _nearest(pr, oid, chain[0], pref) if chain else (_default(pr, oid), "default printing")
    if p is None:
        return {"forge": True, "why": f"not printed in {where}, and no usable scan; AI art", "fallback": True, "pin_missing": pin_missing}
    return {"printing": p, "why": f"not printed in {where}; used {p['set_code'].upper()} ({how}, {p['released_at']})", "fallback": True, "pin_missing": pin_missing}


def basic_arts(pr: Printings, oid: str, set_code: str) -> list[dict]:
    """The distinct arts of a basic land in a set, in collector-number order (for `vary`)."""
    seen, out = set(), []
    for p in sorted(pr.in_sets(oid, [set_code], family=False), key=lambda p: (p["cn_num"], p["cn"])):
        if usable(p) and p["illustration_id"] not in seen and p["treatment"].startswith("regular"):
            seen.add(p["illustration_id"])
            out.append(p)
    return out


def split_copies(n: int, k: int) -> list[int]:
    """10 copies over 4 arts: 3, 3, 2, 2."""
    k = max(1, min(k, n))
    return [n // k + (1 if i < n % k else 0) for i in range(k)]
