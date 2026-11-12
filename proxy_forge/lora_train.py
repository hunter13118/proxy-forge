"""
Person LoRAs, as proxy-forge asks for them. The training itself (captioning the photos, the dataset, the trainer, the checkpoints) is the studio's: proxy-forge sends the photos to its
/v1/ai API and keeps the record that comes back (studio.py `train`). What stays here is proxy-forge's own: the names, the made-up trigger word that stands for a person (so no real name,
and no celebrity, comes along with them), and the number of photos worth asking for.
"""
from __future__ import annotations

import random
import re
import time

MIN_PHOTOS = 6
TARGET_STEPS = 1000            # one step = one photo at batch size 1; the studio's trainer does ~1.4 s a step on the 5090


def make_trigger(seed: str) -> str:
    """A pronounceable made-up word, the same for the same subject: it names the person to the model without any real name."""
    rnd = random.Random(seed)
    cons, vows = "bdfgklmnprstvzx", "aeiou"
    return "".join(rnd.choice(cons) + rnd.choice(vows) for _ in range(3)) + rnd.choice(cons)


def lora_name(subject: dict) -> str:
    return ("pf_" + re.sub(r"[^a-z0-9]+", "_", subject["id"].lower()).strip("_"))[:60]


def epochs_for(n_photos: int, steps: int = TARGET_STEPS) -> int:
    return max(8, min(100, round(steps / max(1, n_photos))))


def train(job, studio, subject: dict, photos: list, steps: int = TARGET_STEPS) -> dict:
    """Has the studio train this subject's LoRA and returns the record to store on the subject: {name, trigger, checkpoints, file, strength, images, epochs, trained_at}."""
    if len(photos) < MIN_PHOTOS:
        raise RuntimeError(f"add at least {MIN_PHOTOS} photos (15 to 30 different ones is better): a LoRA from fewer learns the photos, not the person")
    trigger = (subject.get("lora") or {}).get("trigger") or make_trigger(subject["id"])
    record = studio.train(job, name=lora_name(subject), photos=photos, count_tag=subject.get("count_tag") or "1other", trigger=trigger, steps=steps)
    return {"name": record["name"], "trigger": record.get("trigger", trigger), "checkpoints": record["checkpoints"], "file": record["file"], "strength": record.get("strength", 0.8),
            "images": record.get("images", len(photos)), "epochs": record.get("epochs", 0), "trained_at": record.get("trained_at", time.time())}
