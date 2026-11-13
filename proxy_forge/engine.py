"""
The work, one job at a time (one GPU): importing a deck, describing a person from their photos, writing prompts and drawing art, and re-drawing the cards.

All of the models' work is the studio's (studio.py -> its /v1/ai API). Generating a deck is two phases, so the language model and the picture model take turns on the card: first every
missing prompt is written, then every missing picture is drawn (Anima-Turbo). Art is cached on disk by what was asked for (prompt, seed, size, model, LoRA),
so a re-run only draws what changed; the card is then drawn around the art by the template (render.py), which needs no GPU, so changing the template is instant.
"""
from __future__ import annotations

import hashlib
import json
import logging
import queue
import threading
import time
import uuid
from pathlib import Path

from PIL import Image

from . import config, deck as decklist, export, lora_train, prompts, references, render, resolver, scans, store
from .printings import Printings
from .scryfall import Scryfall, units as card_units
from .studio import Cancelled, Studio

log = logging.getLogger("engine")
SKIP_SECTIONS = {"maybe", "tokens"}


class Job:
    def __init__(self, kind: str, deck: str | None, queue: str = "gpu"):
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.deck, self.queue = kind, deck, queue
        self.state = "queued"                           # queued | running | done | error | cancelled
        self.done, self.total, self.msg, self.error = 0, 0, "queued", ""
        self.cancel = False
        self.created = time.time()

    def public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "queue": self.queue, "deck": self.deck, "state": self.state, "done": self.done, "total": self.total, "message": self.msg, "error": self.error}


def art_dir() -> Path:
    return config.folder("art")


def card_dir(did: str) -> Path:
    return store.deck_dir(did) / "cards"


def safe(key: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in key)


def art_path(art: str) -> Path:
    return art_dir() / Path(art).name


def card_png(did: str, key: str) -> Path:
    return card_dir(did) / f"{safe(key)}.png"


def card_thumb(did: str, key: str) -> Path:
    return card_dir(did) / f"{safe(key)}.thumb.jpg"


class Engine:
    def __init__(self, scry: Scryfall | None = None, studio: Studio | None = None, start: bool = True, printings: Printings | None = None, scan_transport=None):
        self.scry = scry or Scryfall()
        self.prt = printings or Printings()
        self.scan_transport = scan_transport
        self.studio = studio or Studio()
        self.jobs: dict[str, Job] = {}
        self._qs: dict[str, queue.Queue] = {"gpu": queue.Queue(), "net": queue.Queue()}       # "net": Scryfall and image downloads, which never wait behind a LoRA training
        if start:
            for name in self._qs:
                threading.Thread(target=self._worker, args=(name,), daemon=True, name=f"proxy-forge-{name}").start()

    # ------------------------------------------------------------------------------------------------------------------------------------------------- the queue
    def submit(self, kind: str, deck: str | None, fn, queue: str = "gpu") -> Job:
        job = Job(kind, deck, queue)
        self.jobs[job.id] = job
        for old in sorted(self.jobs.values(), key=lambda j: j.created)[:-60]:
            if old.state in ("done", "error", "cancelled"):
                self.jobs.pop(old.id, None)
        self._qs[queue].put((job, fn))
        return job

    def _worker(self, name: str = "gpu") -> None:
        while True:
            job, fn = self._qs[name].get()
            if job.cancel:
                job.state, job.msg = "cancelled", "cancelled"
                continue
            job.state, job.msg = "running", "starting"
            try:
                fn(job)
                job.state, job.msg = ("cancelled", "cancelled") if job.cancel else ("done", job.msg if job.msg not in ("starting", "queued") else "done")
            except Cancelled:
                job.state, job.msg = "cancelled", "cancelled"
            except Exception as e:
                log.exception("job %s failed", job.kind)
                job.state, job.error, job.msg = "error", str(e), str(e)

    # ------------------------------------------------------------------------------------------------------------------------------------------------- importing
    def import_deck(self, did: str, text: str) -> Job:
        return self.submit("import", did, lambda job: self._import(job, did, text))

    def _import(self, job: Job, did: str, text: str) -> None:
        deck = store.get_deck(did)
        entries = [e for e in decklist.parse(text) if e.section not in SKIP_SECTIONS and (deck["include_sideboard"] or e.section != "sideboard")]
        if not entries:
            raise RuntimeError("no card lines found in the deck list")
        job.total = len(entries)
        try:
            job.msg = "checking the Scryfall card data"
            self.scry.refresh_bulk(progress=lambda m: setattr(job, "msg", m))
        except Exception as e:
            log.warning("bulk data unavailable (%s); looking cards up one by one", e)
        units: dict[str, dict] = {}
        order: list[str] = []
        out_entries, missing = [], []
        for i, e in enumerate(entries):
            if job.cancel:
                raise Cancelled()
            job.done, job.msg = i, f"looking up {e.name}"
            card = self.scry.lookup(e.name)
            if card is None:
                missing.append(e.name)
                out_entries.append({"qty": e.qty, "name": e.name, "section": e.section, "found": False, "keys": []})
                continue
            keys = []
            for u in card_units(card):
                k = u["key"]
                keys.append(k)
                pin = {"set": e.set, "number": e.number, "qty": e.qty} if e.set else None
                if k in units:
                    units[k]["copies"] += e.qty
                    if pin:
                        same = next((x for x in units[k]["pins"] if (x["set"], x["number"]) == (pin["set"], pin["number"])), None)
                        if same:
                            same["qty"] += pin["qty"]
                        else:
                            units[k]["pins"].append(pin)
                        units[k]["pin"] = units[k]["pin"] or {"set": pin["set"], "number": pin["number"]}
                    continue
                seed = int(hashlib.sha1((did + k).encode()).hexdigest()[:8], 16)
                units[k] = {**u, "copies": e.qty, "prompt": "", "seed": seed, "subjects": [], "art": "", "art_shape": "", "status": "new", "error": "", "pin": ({"set": e.set, "number": e.number} if e.set else None), "pins": [pin] if pin else []}
                order.append(k)
            out_entries.append({"qty": e.qty, "name": card.get("name", e.name), "section": e.section, "found": True, "keys": keys})

        def apply(d):
            d.update(entries=out_entries, missing=missing, units=units, order=order, status="ready")
        store.update_deck(did, apply)
        job.done = job.total
        job.msg = f"{len(units)} cards" + (f", {len(missing)} not found" if missing else "")
        if resolver.policy_of(store.get_deck(did))["source"] != "forge":
            self.apply_policy(did)                                              # the official art is fetched on the network worker, not behind a drawing

    # ------------------------------------------------------------------------------------------------------------------------------------------------ references
    def describe_subject(self, pid: str, sid: str) -> Job:
        return self.submit("describe", None, lambda job: self._describe(job, pid, sid))

    def _describe(self, job: Job, pid: str, sid: str) -> None:
        p = store.get_profile(pid)
        s = store.get_subject(p, sid) if p else None
        if s is None or not s["photos"]:
            raise RuntimeError("add at least one photo first")
        job.total, job.msg = 1, f"looking at {len(s['photos'])} photo(s)"
        d = references.describe([store.photo_dir(pid, sid) / n for n in s["photos"]], self.studio)
        store.update_subject(pid, sid, {**d, "described": True})
        job.done, job.msg = 1, "described"

    # ------------------------------------------------------------------------------------------------------------------------------------------------- person LoRAs
    def train_subject(self, pid: str, sid: str, steps: int | None = None) -> Job:
        return self.submit("train", None, lambda job: self._train(job, pid, sid, steps))

    def _train(self, job: Job, pid: str, sid: str, steps: int | None) -> None:
        p = store.get_profile(pid)
        s = store.get_subject(p, sid) if p else None
        if s is None:
            raise RuntimeError("no such person")
        photos = [store.photo_dir(pid, sid) / n for n in s["photos"]]
        record = lora_train.train(job, self.studio, s, photos, steps or lora_train.TARGET_STEPS)
        store.update_subject(pid, sid, {"lora": record})
        job.done, job.total, job.msg = 1, 1, f"trained: {record['images']} photos, {record['epochs']} epochs, {len(record['checkpoints'])} checkpoints"

    def preview_lora(self, pid: str, sid: str) -> Job:
        """One picture per saved checkpoint, same prompt and seed, so the best epoch can be chosen by eye."""
        def run(job: Job):
            p = store.get_profile(pid)
            s = store.get_subject(p, sid) if p else None
            if s is None or not s.get("lora"):
                raise RuntimeError("train this person's LoRA first")
            why = self.studio.reachable()
            if why:
                raise RuntimeError(why)
            lo = s["lora"]
            out = store.preview_dir(pid, sid)
            out.mkdir(parents=True, exist_ok=True)
            job.total = len(lo["checkpoints"])
            for n, f in enumerate(lo["checkpoints"]):
                if job.cancel:
                    raise Cancelled()
                job.done, job.msg = n, f"drawing a test with {f}"
                prompt = f"{config.QUALITY}, safe, {s.get("count_tag", "1other")}, {lo["trigger"]}, illustration, upper body, looking at viewer, smile, fantasy adventurer, forest background"
                extra = {}
                if p.get("cartoon_pass", True):
                    tags = p.get("cartoon_tags") or config.CARTOON_TAGS
                    extra = {"restyle_positive": prompts.with_tags(prompt.replace(f"{lo['trigger']}, ", ""), tags), "restyle_denoise": float(p.get("cartoon_strength", config.CARTOON_STRENGTH))}
                    prompt = prompts.with_tags(prompt, tags)
                pic = self.studio.info()["picture"]
                g = {"positive": prompt, "negative": config.NEGATIVE, "width": 832, "height": 1216, "seed": 20240601, "steps": pic["steps"], "cfg": pic["cfg"],
                     "lora": p.get("lora") or "", "lora_strength": float(p.get("lora_strength", 0.8)), "extra_loras": [[f, float(lo.get("strength", 0.8))]], **extra}
                img = self.studio.draw(g, cancelled=lambda: job.cancel)
                img.thumbnail((520, 760))
                img.convert("RGB").save(out / (Path(f).stem + ".jpg"), quality=88)
            job.done, job.msg = job.total, "tests drawn"
        return self.submit("lora-preview", None, run)

    # ------------------------------------------------------------------------------------------------------------------------------------------------ generating
    def generate(self, did: str, keys: list[str] | None = None, rewrite_prompts: bool = False, force: bool = False) -> Job:
        return self.submit("generate", did, lambda job: self._generate(job, did, keys, rewrite_prompts, force))

    def _generate(self, job: Job, did: str, keys, rewrite: bool, force: bool) -> None:
        deck = store.get_deck(did)
        profile = store.get_profile(deck["profile"]) if deck.get("profile") else None
        profile = profile or {"direction": "", "subjects": [], "lora": "", "lora_strength": 0.8}
        tpl = render.get_template(deck["template"])
        shape = render.art_shape(tpl)
        width, height = config.SIZES[shape]
        targets = [k for k in deck["order"] if (keys is None or k in keys) and deck["units"][k].get("art_source", "forge") == "forge"]
        if not targets:
            raise RuntimeError("nothing to draw: every card uses official art (switch a card to AI art in its Loupe, or change the deck's source)")

        # phase 1: the prompts
        need = [k for k in targets if rewrite or not deck["units"][k].get("prompt")]
        job.total = len(need) + len(targets)
        for n, k in enumerate(need):
            if job.cancel:
                raise Cancelled()
            u = deck["units"][k]
            subs = [s for s in profile["subjects"] if s["id"] in u.get("subjects", [])]
            job.done, job.msg = n, f"writing the prompt for {u['name']}"
            scene = prompts.write_scene(u, self.studio, direction=profile.get("direction", ""), subjects=subs)
            text = prompts.compose(scene, subjects=subs, direction=profile.get("direction", ""), shape=shape)
            store.update_deck(did, lambda d, k=k, text=text, scene=scene: d["units"][k].update(prompt=text, scene=scene, status="prompted" if not d["units"][k]["art"] else d["units"][k]["status"]))

        # phase 2: the pictures (the studio frees the language model itself when the card is short of memory)
        why = self.studio.reachable()
        if why:
            raise RuntimeError(why)
        deck = store.get_deck(did)
        failed = 0
        for n, k in enumerate(targets):
            if job.cancel:
                raise Cancelled()
            u = deck["units"][k]
            job.done, job.msg = len(need) + n, f"drawing {u['name']} ({n + 1}/{len(targets)})"
            try:
                subs = [s for s in profile["subjects"] if s["id"] in u.get("subjects", [])]
                art = self._draw(job, u, profile, width, height, force, subs)
                store.update_deck(did, lambda d, k=k, art=art: d["units"][k].update(art=art, art_shape=shape, status="drawn", error=""))
            except Cancelled:
                raise
            except Exception as e:
                failed += 1
                log.warning("drawing %s failed: %s", u["name"], e)
                store.update_deck(did, lambda d, k=k, e=e: d["units"][k].update(status="error", error=str(e)[:300]))
            self.render_unit(did, k)
        job.done = job.total
        job.msg = f"drew {len(targets) - failed} of {len(targets)}" + (f" ({failed} failed)" if failed else "")
        if failed == len(targets):
            raise RuntimeError(job.msg + ": " + (store.get_deck(did)["units"][targets[0]].get("error") or "see the log"))

    def graph_params(self, unit: dict, profile: dict, width: int, height: int, subjects: list[dict] | None = None) -> dict:
        subjects = subjects or []
        extra = [[s["lora"]["file"], float(s["lora"].get("strength", 0.8))] for s in subjects if s.get("lora") and s["lora"].get("file")]       # the people's own LoRAs, stacked on the style LoRA
        positive = prompts.with_triggers(unit["prompt"], subjects)
        pic = self.studio.info()["picture"]                                          # the studio's picture model sets the model, steps and CFG; they are part of what the art is cached by
        params = {"positive": positive, "negative": config.NEGATIVE, "width": width, "height": height, "seed": int(unit["seed"]), "steps": pic["steps"],
                  "cfg": pic["cfg"], "unet": pic["unet"], "lora": profile.get("lora") or "", "lora_strength": float(profile.get("lora_strength", 0.8)), "extra_loras": extra}
        if extra and profile.get("cartoon_pass", True):                           # a person's LoRA was trained on photos: keep the picture a cartoon (words, then a second pass without it)
            tags = profile.get("cartoon_tags") or config.CARTOON_TAGS
            params["positive"] = prompts.with_tags(positive, tags)
            params["restyle_positive"] = prompts.with_tags(unit["prompt"], tags)
            params["restyle_denoise"] = float(profile.get("cartoon_strength", config.CARTOON_STRENGTH))
        return params

    def _draw(self, job: Job, unit: dict, profile: dict, width: int, height: int, force: bool, subjects: list[dict] | None = None) -> str:
        params = self.graph_params(unit, profile, width, height, subjects)
        name = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:20] + ".png"
        path = art_dir() / name
        if force or not path.exists():
            img = self.studio.draw(params, cancelled=lambda: job.cancel)
            tmp = path.with_suffix(".part")
            img.save(tmp, "PNG")
            tmp.replace(path)
        return name

    # ------------------------------------------------------------------------------------------------------------------------------------------- official art (Archive)
    def ensure_index(self, progress=lambda m: None, max_age: float | None = None) -> None:
        """Build the printings index when there is none (or, for prices, when it is over a day old)."""
        if not self.prt.ready() or (max_age is not None and self.prt.stale(max_age)):
            self.prt.build(progress)

    def apply_policy(self, did: str, policy: dict | None = None) -> Job:
        """Save the art policy (when given) and resolve every card to a printing, fetch the scans and redraw the cards. Runs on the network worker."""
        return self.submit("art", did, lambda job: self._apply(job, did, policy), queue="net")

    def _apply(self, job: Job, did: str, policy: dict | None) -> None:
        if policy is not None:
            store.update_deck(did, lambda d: d.update(art_policy=policy))
        pol = resolver.policy_of(store.get_deck(did))
        if pol["source"] != "forge":
            job.msg = "checking the printings index"
            self.ensure_index(lambda m: setattr(job, "msg", m), 86400 if pol["source"] in ("vault", "budget") else None)
        changes = resolve_deck(self.prt, store.get_deck(did), pol) if pol["source"] == "forge" or self.prt.ready() else None
        store.update_deck(did, lambda d: d.update(units=changes["units"], order=changes["order"]))
        deck = store.get_deck(did)
        want = []
        for k in deck["order"]:
            u = deck["units"][k]
            if u.get("art_source", "forge") != "forge" and u.get("printing"):
                full = self._printing_row(u["printing"]["id"])
                want.append((full, int(u.get("face", 0)), "png"))
                if pol["print"] == "template":
                    want.append((full, int(u.get("face", 0)), "art_crop"))
        want = list({(w[0]["id"], w[1], w[2]): w for w in want}.values())
        job.total, job.done = len(want) + len(deck["order"]), 0
        job.msg = f"fetching {len(want)} card images"
        errors = scans.fetch_many(want, lambda d, t: setattr(job, "done", d), transport=self.scan_transport)
        for n, k in enumerate(deck["order"]):
            if job.cancel:
                raise Cancelled()
            job.done, job.msg = len(want) + n, f"drawing {deck['units'][k]['name']}"
            self.render_unit(did, k)
        n_fb = sum(1 for k in deck["order"] if (deck["units"][k].get("printing") or {}).get("fallback"))
        job.done = job.total
        job.msg = f"{len(deck['order'])} cards" + (f", {n_fb} not in the chosen sets" if n_fb else "") + (f", {len(errors)} images failed" if errors else "")
        if errors:
            log.warning("scan errors: %s", errors[:5])

    def _printing_row(self, pid: str) -> dict:
        with self.prt._db() as db:
            row = db.execute("select * from printings where id=?", (pid,)).fetchone()
        if row is None:
            raise RuntimeError("no such printing")
        return dict(row)

    def set_printing(self, did: str, key: str, printing_id: str | None) -> Job:
        """Hang one card on a printing chosen by hand (or on AI art when `printing_id` is None). Re-resolving the deck leaves it alone."""
        def run(job: Job):
            deck = store.get_deck(did)
            u = deck["units"][key]
            if printing_id is None:
                store.update_deck(did, lambda d: d["units"][key].update(art_source="forge", printing=None, locked=True, note="AI art, chosen by hand"))
            else:
                p = self._printing_row(printing_id)
                pb = {**resolver.brief(p), "why": "chosen by hand", "fallback": False}
                job.msg = "fetching the image"
                scans.fetch(p, int(u.get("face", 0)), "png", self.scan_transport)
                if resolver.policy_of(deck)["print"] == "template":
                    scans.fetch(p, int(u.get("face", 0)), "art_crop", self.scan_transport)
                src = u.get("art_source", "forge")
                src = src if src != "forge" else (resolver.policy_of(deck)["source"] if resolver.policy_of(deck)["source"] != "forge" else "archive")
                store.update_deck(did, lambda d: d["units"][key].update(art_source=src, printing=pb, locked=True, note=""))
            self.render_unit(did, key)
            job.done = job.total = 1
            job.msg = "hung"
        return self.submit("pin", did, run, queue="net")

    # --------------------------------------------------------------------------------------------------------------------------------------------------- rendering
    def render_unit(self, did: str, key: str) -> None:
        deck = store.get_deck(did)
        u = deck["units"][key]
        tpl = render.get_template(deck["template"])
        card = self._official_card(deck, u, tpl)
        if card is None:
            art = None
            if u.get("art") and art_path(u["art"]).exists():
                with Image.open(art_path(u["art"])) as im:
                    art = im.convert("RGB")
            card = render.render(u, art, tpl)
        card_dir(did).mkdir(parents=True, exist_ok=True)
        card.save(card_png(did, key), "PNG")
        card.resize((360, 504), Image.LANCZOS).save(card_thumb(did, key), "JPEG", quality=88)

    def _official_card(self, deck: dict, u: dict, tpl: dict) -> Image.Image | None:
        """The card from Scryfall's picture (the whole scan, or its art in the template), or None when the card is AI art or its image has not arrived."""
        pr = u.get("printing")
        if u.get("art_source", "forge") == "forge" or not pr:
            return None
        face = int(u.get("face", 0))
        if resolver.policy_of(deck)["print"] == "template":
            crop = scans.path_for(pr, face, "art_crop")
            if not crop.exists():
                return None
            with Image.open(crop) as im:
                art = im.convert("RGB")
            return render.render(u, art, tpl, footer_text=f"Illus. {pr.get('artist') or '?'}  |  TM & (c) Wizards of the Coast  |  PROXY, not for sale")
        scan = scans.path_for(pr, face, "png")
        return scans.official(scan) if scan.exists() else None

    def ensure_card(self, did: str, key: str, thumb: bool = False) -> Path:
        """The card's picture, drawn now if it is missing or older than the drawing code and templates."""
        png, small = card_png(did, key), card_thumb(did, key)
        want = small if thumb else png
        stamp = render.stamp()
        if not (png.exists() and small.exists()) or min(png.stat().st_mtime, small.stat().st_mtime) < stamp:
            self.render_unit(did, key)
        return want

    def render_deck(self, did: str) -> Job:
        def run(job: Job):
            deck = store.get_deck(did)
            job.total = len(deck["order"])
            for n, k in enumerate(deck["order"]):
                if job.cancel:
                    raise Cancelled()
                job.done, job.msg = n, f"drawing the card {deck['units'][k]['name']}"
                self.render_unit(did, k)
            job.done, job.msg = job.total, "cards redrawn"
        return self.submit("render", did, run)

    def card_images(self, did: str, copies: bool = True, skip_basics: bool = False) -> list[tuple[str, Path]]:
        """(file name, card picture) for each card in print order, repeated by the number of copies in the deck list when `copies`; basic lands left out when `skip_basics` (saves sheets)."""
        deck = store.get_deck(did)
        out = []
        for k in deck["order"]:
            u = deck["units"][k]
            if skip_basics and export.is_basic_land(u["name"]):
                continue
            p = self.ensure_card(did, k)
            for c in range(u["copies"] if copies else 1):
                out.append((f"{len(out) + 1:03d} {render_safe(u['name'])}.png", p))
        return out


def print_shop_images(eng: "Engine", did: str, copies: bool) -> list[tuple[str, Image.Image]]:
    """822x1122 pictures with 1/8 in bleed, named with where each card's art came from: `001 Sol Ring [CMM 410].png`."""
    deck = store.get_deck(did)
    out = []
    for k in deck["order"]:
        u = deck["units"][k]
        p = u.get("printing") or {}
        tag = f" [{p['set'].upper()} {p['cn']}]" if p else " [AI]"
        full = "borderless" in p.get("treatment", "") or "fullart" in p.get("treatment", "") or (u.get("art_source", "forge") == "forge" and render.get_template(deck["template"]).get("style") == "fullart")
        with Image.open(eng.ensure_card(did, k)) as im:
            bled = export.with_bleed(im, mirror=full)
        for _ in range(u["copies"] if copies else 1):
            out.append((f"{len(out) + 1:03d} {render_safe(u['name'])}{tag}.png".replace("/", "-"), bled))
    return out


def render_safe(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in " -_'").strip()[:60]


def resolve_deck(pr: Printings, deck: dict, pol: dict) -> dict:
    """Give every card of the deck its printing under `pol`. Returns {"units", "order"} (the deck's own dicts are not changed). Cards the owner hung by hand (`locked`) keep their pick.
    Basic lands with several copies are spread over the set's different arts: the card is split into `key#a`, `key#b` ... each with its share of the copies."""
    units = {k: dict(u) for k, u in deck["units"].items()}
    order = list(deck["order"])
    for base, u in list(units.items()):                                        # undo an earlier split
        subs = u.get("split")
        if subs:
            at = min((order.index(s) for s in subs if s in order), default=len(order))
            order = [k for k in order if k not in subs]
            order.insert(at, base)
            for s in subs:
                units.pop(s, None)
            u.pop("split", None)
    out_order: list[str] = []
    for k in order:
        u = units[k]
        if u.get("locked"):
            out_order.append(k)
            continue
        if pol["source"] == "forge":
            u.update(art_source="forge", printing=None, note="")
            out_order.append(k)
            continue
        pins = [x for x in u.get("pins") or [] if pol.get("pins", True)]
        if len(pins) > 1 or (pins and pins[0]["qty"] < u.get("copies", 1)):
            subs, rest = [], u["copies"] - sum(x["qty"] for x in pins)
            groups = [(x, x["qty"]) for x in pins] + ([({"set": "", "number": ""}, rest)] if rest > 0 else [])
            for i, (x, n) in enumerate(groups):
                sk = f"{k}#{chr(97 + i)}"
                sub = {**u, "key": sk, "copies": n, "split_of": k, "pin": ({"set": x["set"], "number": x["number"]} if x["set"] else None), "pins": []}
                r = resolver.resolve_unit(pr, sub, pol) if pol["source"] == "archive" or x["set"] else None
                if r is None and pol["source"] in ("vault", "budget"):
                    from . import vault
                    r = vault.pick(pr, sub, pol)
                if r.get("printing") is None:
                    sub.update(art_source="forge", printing=None, note=r["why"])
                else:
                    sub.update(art_source=pol["source"], printing={**resolver.brief(r["printing"]), "why": r["why"], "fallback": r["fallback"], "pin_missing": r.get("pin_missing", False)}, note="", price=r.get("price"))
                units[sk] = sub
                subs.append(sk)
            u["split"] = subs
            out_order.extend(subs)
            continue
        if pol["source"] in ("vault", "budget"):
            from . import vault
            res = vault.pick(pr, u, pol)
        else:
            res = resolver.resolve_unit(pr, u, pol)
        if res.get("printing") is None:
            u.update(art_source="forge", printing=None, note=res["why"] + (" (pinned line not found)" if res.get("pin_missing") else ""))
            out_order.append(k)
            continue
        oid = res["printing"]["oracle_id"]
        arts = []
        if pol.get("vary_basics", True) and pol["source"] == "archive" and resolver.is_basic(u) and u.get("copies", 1) > 1 and not res["fallback"]:
            arts = resolver.basic_arts(pr, oid, res["printing"]["set_code"])
        if len(arts) > 1:
            counts = resolver.split_copies(u["copies"], len(arts))
            subs = []
            for i, (p, n) in enumerate(zip(arts, counts)):
                sk = f"{k}#{chr(97 + i)}"
                units[sk] = {**u, "key": sk, "copies": n, "split_of": k, "art_source": pol["source"], "printing": {**resolver.brief(p), "why": res["why"], "fallback": False}, "note": ""}
                subs.append(sk)
            u["split"] = subs
            out_order.extend(subs)
            continue
        u.update(art_source=pol["source"], printing={**resolver.brief(res["printing"]), "why": res["why"], "fallback": res["fallback"], "pin_missing": res.get("pin_missing", False)},
                 note="", price=res.get("price"))
        out_order.append(k)
    return {"units": units, "order": out_order}
