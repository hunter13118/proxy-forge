"""
Turning a card into a picture prompt for Anima, which reads Danbooru-style tags and plain sentences.

The studio's language model reads the card and writes the scene; the subjects the user assigned to the card (friends, described from their photos: references.py) are put in
verbatim, so their hair, glasses and so on are always in the prompt; the style profile's verbal direction is carried through. With no language model, a plain fallback is used.
"""
from __future__ import annotations

import logging
import re

from . import config
from .studio import Studio

log = logging.getLogger("prompts")

SYSTEM = (
    "You write picture prompts for an anime-style illustration model that reads Danbooru tags and plain English sentences. You are given a Magic: The Gathering card; "
    "write the scene for its artwork: what the picture shows, not the card's rules. Rules: show the card's own subject (a creature, a person, an object, a place) clearly and "
    "dramatically; for a land or a place show the scenery with no characters; for a spell show the moment it happens; never write card names as text in the picture, never mention "
    "cards, frames, borders, mana or game terms; keep it safe for work. If the user lists characters that must appear, the picture's main character IS that person: use their "
    "description exactly and fit them into the card's role (dress and pose them as the creature type or the spell's caster). Follow the style direction if one is given. "
    'Answer with JSON only: {"scene": "one or two plain sentences", "tags": ["10 to 16 short Danbooru-style tags: subject, pose, clothing, setting, lighting, mood"]}'
)


def _count_tags(subjects: list[dict]) -> list[str]:
    boys = sum(1 for s in subjects if s.get("count_tag") in ("1boy", "boy"))
    girls = sum(1 for s in subjects if s.get("count_tag") in ("1girl", "girl"))
    out = []
    if girls:
        out.append("1girl" if girls == 1 else f"{girls}girls")
    if boys:
        out.append("1boy" if boys == 1 else f"{boys}boys")
    return out


GAME_WORDS = ("mana", "upkeep", "deathtouch", "lifelink", "trample", "life", "card", "spell", "token", "graveyard", "battlefield", "counter", "cmc")


def _clean_tags(raw) -> list[str]:
    """The writer's tags with hyphens as spaces, game words dropped (the picture should not try to draw rules), and no repeats."""
    out, seen = [], set()
    for t in raw:
        t = re.sub(r"[-_]+", " ", str(t)).strip().lower()
        if t and t not in seen and not set(t.split()) & set(GAME_WORDS):
            seen.add(t)
            out.append(t)
    return out[:16]


def _fallback_scene(unit: dict) -> dict:
    t = unit.get("type_line", "")
    name = unit.get("name", "")
    if "Land" in t:
        return {"scene": f"A sweeping fantasy landscape: {name}.", "tags": ["scenery", "no humans", "fantasy", "landscape", "wide shot", "detailed background", "atmospheric lighting"]}
    if "Creature" in t:
        kind = t.split("—")[-1].strip().lower() if "—" in t else "creature"
        return {"scene": f"A {kind} named {name}, in a dramatic pose.", "tags": ["solo", "fantasy", kind, "dynamic pose", "detailed background", "dramatic lighting"]}
    return {"scene": f"{name}: a dramatic fantasy scene.", "tags": ["fantasy", "dramatic lighting", "detailed background", "magic", "scenery"]}


def write_scene(unit: dict, studio: Studio, *, direction: str = "", subjects: list[dict] | None = None) -> dict:
    subjects = subjects or []
    colors = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
    lines = [f"Card name: {unit.get('name', '')}", f"Type: {unit.get('type_line', '')}"]
    if unit.get("colors"):
        lines.append("Colours: " + ", ".join(colors.get(c, c) for c in unit["colors"]))
    if unit.get("oracle_text"):
        lines.append("Rules text: " + unit["oracle_text"][:600].replace("\n", " / "))
    if unit.get("flavor_text"):
        lines.append("Flavour text: " + unit["flavor_text"][:200])
    if direction.strip():
        lines.append("Style direction from the user: " + direction.strip())
    for s in subjects:
        lines.append(f"A character that must appear as the main character (never write a name for them) looks like: {s.get('sentence', '')} ({', '.join(s.get('tags', []))})")
    try:
        out = studio.chat_json("\n".join(lines), system=SYSTEM, timeout=240, temperature=0.8)
        tags = _clean_tags(out.get("tags", []))
        scene = str(out.get("scene", "")).strip()
        if scene and tags:
            return {"scene": scene, "tags": tags}
    except Exception as e:
        log.warning("scene writer failed for %s: %s", unit.get("name"), e)
    return _fallback_scene(unit)


def with_triggers(prompt: str, subjects: list[dict]) -> str:
    """Put the trigger words of the subjects' trained LoRAs into a prompt (at draw time, so a LoRA trained after the prompt was written still takes effect). 'illustration' keeps the LoRA's photo look out."""
    trig = [s["lora"]["trigger"] for s in subjects if s.get("lora") and s["lora"].get("trigger") and s["lora"]["trigger"] not in prompt]
    if not trig:
        return prompt
    head = config.QUALITY + ", "
    add = ", ".join(trig) + ", illustration"
    return prompt.replace(head, head + add + ", ", 1) if prompt.startswith(head) else add + ", " + prompt


def with_tags(prompt: str, tags: str) -> str:
    """Style words right after the quality words (where Anima reads them most strongly), unless they are already in."""
    tags = (tags or "").strip().strip(",")
    if not tags or tags in prompt:
        return prompt
    head = config.QUALITY + ", "
    return prompt.replace(head, head + tags + ", ", 1) if prompt.startswith(head) else tags + ", " + prompt


def compose(scene: dict, *, subjects: list[dict] | None = None, direction: str = "", shape: str = "landscape", no_humans: bool = False) -> str:
    """The final prompt: quality words, who is in it, the writer's tags, the subjects' own description (always), the scene sentence, and the style direction."""
    subjects = subjects or []
    parts = [config.QUALITY] + _count_tags(subjects)
    seen = set(p.lower() for p in parts)
    for t in scene.get("tags", []) + [t for s in subjects for t in s.get("tags", [])]:
        if t.lower() not in seen:
            seen.add(t.lower())
            parts.append(t)
    parts.append("full bleed illustration, filling the entire frame")                  # without this the model sometimes draws a narrow panel on a white page
    text = ", ".join(p for p in parts if p)
    sentences = [scene.get("scene", "")] + [f"The main character looks like this: {s.get('sentence', '')}." for s in subjects if s.get("sentence")]
    if direction.strip():
        sentences.append(f"Art style: {direction.strip()}")
    return re.sub(r"\s+", " ", text + ". " + " ".join(x for x in sentences if x)).strip()
