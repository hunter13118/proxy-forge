"""
Vault: the most expensive art variant of each card (and Budget: the cheapest).

A variant is one illustration in one treatment (printings.variants), so the winner looks different from the others, not just the foil copy of the same card. Prices come from the
printings index (Scryfall's daily `usd`, `usd_foil`, `usd_etched`, `eur`, `eur_foil`: TCGplayer and Cardmarket). Every pick carries its reasoning (price, finish, provider, date); prices
are a daily snapshot and never called live.

Switches (policy["vault"]): currency usd|eur, foil (let foil/etched prices count), serialized (numbered cards may win), odd (oversized/gold-border may win), scope (only variants printed
in the Archive set chain). Unpriced variants are never chosen unless every variant is unpriced.
"""
from __future__ import annotations

import json
import time

from . import resolver
from .printings import Printings

PROVIDER = {"usd": "tcgplayer", "eur": "cardmarket"}


def printing_price(p: dict, v: dict) -> tuple[float, str] | None:
    """(amount, finish) of one printing: the highest of the finishes that exist and are allowed."""
    cur = v.get("currency", "usd")
    finishes = json.loads(p["finishes"]) if isinstance(p["finishes"], str) else (p["finishes"] or [])
    opts = []
    if cur == "usd":
        if "nonfoil" in finishes and p["usd"] is not None:
            opts.append((p["usd"], "nonfoil"))
        if v.get("foil", True):
            if "foil" in finishes and p["usd_foil"] is not None:
                opts.append((p["usd_foil"], "foil"))
            if "etched" in finishes and p["usd_etched"] is not None:
                opts.append((p["usd_etched"], "etched"))
    else:
        if "nonfoil" in finishes and p["eur"] is not None:
            opts.append((p["eur"], "nonfoil"))
        if v.get("foil", True) and "foil" in finishes and p["eur_foil"] is not None:
            opts.append((p["eur_foil"], "foil"))
    return max(opts) if opts else None


def allowed(p: dict, v: dict) -> bool:
    promos = json.loads(p["promo_types"] or "[]")
    if not v.get("serialized", False) and "serialized" in promos:
        return False
    if not v.get("odd", False) and (p["border_color"] == "gold" or p["oversized"]):
        return False
    return True


def appraise(pr: Printings, oid: str, pol: dict) -> list[dict]:
    """The card's art variants with prices, best first (highest for Vault, lowest for Budget). Unpriced variants come last."""
    v = pol.get("vault", {})
    chain = set(pr.family([c.lower() for c in pol.get("sets", [])])) if v.get("scope") and pol.get("sets") else None
    out = []
    for var in pr.variants(oid):
        ps = [p for p in var["printings"] if allowed(p, v) and resolver.usable(p)]
        if chain is not None:
            ps = [p for p in ps if p["set_code"] in chain]
        if not ps:
            continue
        priced = [(printing_price(p, v), p) for p in ps]
        priced = [(pp, p) for pp, p in priced if pp]
        best_img = sorted(ps, key=lambda p: (-resolver.STATUS_RANK.get(p["image_status"], 0), _desc(p["released_at"])))[0]
        top = max(priced, key=lambda x: x[0][0]) if priced else None
        out.append({"treatment": var["treatment"], "illustration_id": var["illustration_id"], "printing": best_img, "amount": top[0][0] if top else None,
                    "finish": top[0][1] if top else None, "priced_in": top[1]["set_code"] if top else None, "n": len(ps)})
    cheapest = pol.get("source") == "budget"
    priced = sorted([x for x in out if x["amount"] is not None], key=lambda x: (x["amount"] if cheapest else -x["amount"], -resolver.STATUS_RANK.get(x["printing"]["image_status"], 0)))
    return priced + [x for x in out if x["amount"] is None]


def _desc(s):
    return tuple(-ord(c) for c in (s or ""))


def as_of(pr: Printings) -> str:
    try:
        with pr._db() as db:
            t = float(db.execute("select v from meta where k='built_at'").fetchone()[0])
        return time.strftime("%Y-%m-%d", time.gmtime(t))
    except Exception:
        return ""


def pick(pr: Printings, unit: dict, pol: dict) -> dict:
    """The Vault (or Budget) choice for one card, as a resolver result with `price`."""
    oid = resolver.oracle_of(pr, unit)
    if oid is None:
        return {"forge": True, "why": "card not in the printings index", "fallback": True}
    ranked = appraise(pr, oid, pol)
    cur = pol.get("vault", {}).get("currency", "usd")
    if not ranked or ranked[0]["amount"] is None:
        fb = resolver.resolve_unit(pr, unit, {**pol, "source": "archive"}) if pol.get("sets") else {"forge": True, "why": "no price data", "fallback": True}
        fb["why"] = "no price data; " + fb["why"]
        fb["fallback"] = True
        return fb
    top = ranked[0]
    price = {"amount": top["amount"], "currency": cur, "finish": top["finish"], "provider": PROVIDER[cur], "via": "scryfall", "as_of": as_of(pr),
             "runners_up": [r["printing"]["id"] for r in ranked[1:3] if r["amount"] is not None]}
    word = "cheapest" if pol.get("source") == "budget" else "priciest"
    return {"printing": top["printing"], "why": f"{word} of {len(ranked)} art variants", "fallback": False, "price": price}
