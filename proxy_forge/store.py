"""Profiles (style direction, subjects with their photos, optional LoRA) and decks, as JSON files under the data folder (G:). One lock for all writes."""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import config

LOCK = threading.RLock()
PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp"}


def _slug(s: str, fallback: str = "x") -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40] or fallback


def _read(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


# ---------------------------------------------------------------------------------------------------------------------------------------------------------- profiles

def profile_dir(pid: str) -> Path:
    return config.folder("profiles", pid)


def new_profile(name: str) -> dict:
    with LOCK:
        pid = f"{_slug(name, 'style')}-{uuid.uuid4().hex[:6]}"
        p = {"id": pid, "name": name or "New style", "direction": "", "lora": "", "lora_strength": 0.8, "subjects": [], "created": time.time()}
        _write(profile_dir(pid) / "profile.json", p)
        return p


def get_profile(pid: str) -> dict | None:
    return _read(config.DATA / "profiles" / pid / "profile.json")


def list_profiles() -> list[dict]:
    d = config.DATA / "profiles"
    return sorted((p for p in (_read(f) for f in d.glob("*/profile.json")) if p), key=lambda p: p.get("created", 0)) if d.is_dir() else []


def save_profile(p: dict) -> dict:
    with LOCK:
        _write(profile_dir(p["id"]) / "profile.json", p)
    return p


def update_profile(pid: str, fields: dict) -> dict:
    with LOCK:
        p = get_profile(pid)
        if p is None:
            raise KeyError(pid)
        for k in ("name", "direction", "lora", "lora_strength", "cartoon_pass", "cartoon_strength", "cartoon_tags"):
            if k in fields:
                p[k] = fields[k]
        return save_profile(p)


def delete_profile(pid: str) -> None:
    with LOCK:
        shutil.rmtree(config.DATA / "profiles" / pid, ignore_errors=True)


def add_subject(pid: str, name: str) -> dict:
    with LOCK:
        p = get_profile(pid)
        if p is None:
            raise KeyError(pid)
        s = {"id": f"{_slug(name, 'person')}-{uuid.uuid4().hex[:5]}", "name": name or "Person", "photos": [], "tags": [], "sentence": "", "count_tag": "1other", "described": False}
        p["subjects"].append(s)
        save_profile(p)
        return s


def get_subject(p: dict, sid: str) -> dict | None:
    return next((s for s in p["subjects"] if s["id"] == sid), None)


def update_subject(pid: str, sid: str, fields: dict) -> dict:
    with LOCK:
        p = get_profile(pid)
        s = get_subject(p, sid) if p else None
        if s is None:
            raise KeyError(sid)
        for k in ("name", "tags", "sentence", "count_tag", "described", "lora"):
            if k in fields:
                s[k] = fields[k]
        save_profile(p)
        return s


def preview_dir(pid: str, sid: str) -> Path:
    return profile_dir(pid) / "previews" / sid


def update_lora(pid: str, sid: str, fields: dict) -> dict:
    """Change the chosen checkpoint / strength of a subject's trained LoRA."""
    with LOCK:
        p = get_profile(pid)
        s = get_subject(p, sid) if p else None
        if s is None or not s.get("lora"):
            raise KeyError(sid)
        if "file" in fields and fields["file"] in s["lora"]["checkpoints"]:
            s["lora"]["file"] = fields["file"]
        if "strength" in fields:
            s["lora"]["strength"] = max(0.0, min(1.5, float(fields["strength"])))
        save_profile(p)
        return s["lora"]


def delete_subject(pid: str, sid: str) -> None:
    with LOCK:
        p = get_profile(pid)
        if p is None:
            return
        p["subjects"] = [s for s in p["subjects"] if s["id"] != sid]
        save_profile(p)
        shutil.rmtree(profile_dir(pid) / "photos" / sid, ignore_errors=True)


def photo_dir(pid: str, sid: str) -> Path:
    return profile_dir(pid) / "photos" / sid


def add_photo(pid: str, sid: str, filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in PHOTO_TYPES:
        raise ValueError("photos must be .jpg, .png or .webp")
    with LOCK:
        p = get_profile(pid)
        s = get_subject(p, sid) if p else None
        if s is None:
            raise KeyError(sid)
        name = f"{uuid.uuid4().hex[:8]}{ext}"
        d = photo_dir(pid, sid)
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(data)
        s["photos"].append(name)
        s["described"] = False
        save_profile(p)
        return name


def delete_photo(pid: str, sid: str, name: str) -> None:
    with LOCK:
        p = get_profile(pid)
        s = get_subject(p, sid) if p else None
        if s is None:
            return
        s["photos"] = [x for x in s["photos"] if x != name]
        (photo_dir(pid, sid) / Path(name).name).unlink(missing_ok=True)
        save_profile(p)


# --------------------------------------------------------------------------------------------------------------------------------------------------------------- decks

def deck_dir(did: str) -> Path:
    return config.folder("decks", did)


def new_deck(name: str, profile: str, template: str, include_sideboard: bool) -> dict:
    with LOCK:
        did = f"{_slug(name, 'deck')}-{uuid.uuid4().hex[:6]}"
        d = {"id": did, "name": name or "Deck", "created": time.time(), "profile": profile, "template": template, "include_sideboard": include_sideboard,
             "entries": [], "missing": [], "order": [], "units": {}, "status": "importing"}
        _write(deck_dir(did) / "deck.json", d)
        return d


def get_deck(did: str) -> dict | None:
    return _read(config.DATA / "decks" / did / "deck.json")


def save_deck(d: dict) -> dict:
    with LOCK:
        _write(deck_dir(d["id"]) / "deck.json", d)
    return d


def update_deck(did: str, fn) -> dict:
    """Read-modify-write under the lock: `fn(deck)` changes the dict in place."""
    with LOCK:
        d = get_deck(did)
        if d is None:
            raise KeyError(did)
        fn(d)
        return save_deck(d)


def list_decks() -> list[dict]:
    root = config.DATA / "decks"
    out = []
    for f in root.glob("*/deck.json") if root.is_dir() else []:
        d = _read(f)
        if d:
            drawn = sum(1 for u in d["units"].values() if u.get("art"))
            out.append({"id": d["id"], "name": d["name"], "created": d.get("created", 0), "profile": d.get("profile"), "template": d.get("template"), "status": d.get("status"),
                        "cards": len(d["units"]), "drawn": drawn})
    return sorted(out, key=lambda d: -d["created"])


def delete_deck(did: str) -> None:
    with LOCK:
        shutil.rmtree(config.DATA / "decks" / did, ignore_errors=True)
