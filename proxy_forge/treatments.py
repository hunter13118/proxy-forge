"""
What a printing looks like, as one short key.

Two printings are the same *art variant* when they share the illustration and this key (see printings.variants). The key is built from the things that change the look of the
card on paper: a non-black border, the frame effects that restyle it (showcase, extended art, etched, inverted ...), full art and textless. A plain card is `regular-<frame>`
(`regular-2015`). Foil finishes are not part of the key: a foil of the same printing looks the same on a flat scan. `look_promos=True` adds the promo types that do change the
look (galaxy foil, surge foil, textured ...) for owners who count finish as treatment.
"""
from __future__ import annotations

EFFECTS = {"showcase": "showcase", "extendedart": "extended", "etched": "etched", "inverted": "inverted", "shatteredglass": "shattered", "fullart": "fullart", "textless": "textless",
           "borderless": "borderless", "gilded": "gilded", "tombstone": "tombstone", "enchantment": "enchantment", "snow": "snow", "miracle": "miracle", "draft": "draft",
           "devoid": None, "legendary": None, "companion": None, "nyxtouched": None, "colorshifted": "colorshifted", "waxing_and_waning": "wane", "upsidedown": "upsidedown",
           "spacecraft": None, "vehicle": None, "convertdfc": None, "sundiscdfc": None, "moondfc": None, "originpwdfc": None, "fandfc": None, "mooneldrazidfc": None, "compasslanddfc": None}
LOOK_PROMOS = {"textured", "galaxyfoil", "surgefoil", "rainbowfoil", "oilslick", "stepandcompleat", "confettifoil", "halofoil", "neonink", "doubleexposure", "ripplefoil",
               "fracturefoil", "mosaicfoil", "raisedfoil", "gilded", "embossed", "chocobotrackfoil", "silverfoil"}
ORDER = ["borderless", "white", "gold", "silver", "yellow", "bronze", "showcase", "extended", "etched", "inverted", "shattered", "fullart", "textless"]


def parts(card: dict, look_promos: bool = False) -> list[str]:
    out: set[str] = set()
    border = card.get("border_color") or "black"
    if border != "black":
        out.add(border)
    for fx in card.get("frame_effects") or []:
        key = EFFECTS.get(fx, fx)                       # an effect we have not met: kept as it is, so two looks never merge by accident
        if key:
            out.add(key)
    if card.get("full_art"):
        out.add("fullart")
    if card.get("textless"):
        out.add("textless")
    if look_promos:
        out.update(p for p in card.get("promo_types") or [] if p in LOOK_PROMOS)
    return sorted(out, key=lambda p: (ORDER.index(p) if p in ORDER else len(ORDER), p))


def treatment(card: dict, look_promos: bool = False) -> str:
    """`borderless`, `showcase`, `borderless-showcase`, `extended`, `regular-2015` ..."""
    p = parts(card, look_promos)
    return "-".join(p) if p else f"regular-{card.get('frame') or '2015'}"


def label(card: dict, look_promos: bool = False) -> str:
    """For the page: `Borderless · Showcase`, `Regular · 2015`."""
    p = parts(card, look_promos)
    return " · ".join(x.capitalize() for x in p) if p else f"Regular · {card.get('frame') or '2015'}"


def is_regular(key: str) -> bool:
    return key.startswith("regular")
