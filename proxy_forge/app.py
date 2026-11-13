"""The web app: a small JSON API over the engine, and the page (web/). Loopback only unless PROXY_NO_AUTH=1 says the network is trusted; tunnel sign-in is a later step."""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel
from studio_kit import web_auth

from . import backs, config, export, importers, lora_train, render, resolver, scans, store, vault
from .studio import StudioError
from .engine import Engine, art_path, card_png, card_thumb, safe

logging.basicConfig(level=logging.INFO)
WEB_DIR = Path(__file__).resolve().parent / "web"


class NoStoreStatic(StaticFiles):
    """The page's files with `Cache-Control: no-store`, so neither the browser nor Cloudflare's edge (which keeps .js and .css for hours by default) serves an old copy after a change."""

    def file_response(self, *args, **kw):
        r = super().file_response(*args, **kw)
        r.headers["Cache-Control"] = "no-store"
        return r


class DeckIn(BaseModel):
    name: str = "My deck"
    text: str
    profile: str = ""
    template: str = "classic"
    include_sideboard: bool = False
    art_policy: dict | None = None


class ArtPolicyIn(BaseModel):
    source: str = "archive"
    sets: list[str] = []
    family: bool = True
    treatment: str = "regular"
    pins: bool = True
    fallback: str = "nearest"
    vary_basics: bool = True
    vault: dict = {}
    print: str = "scan"


class PrintingIn(BaseModel):
    printing_id: str | None = None


class BackIn(BaseModel):
    mode: str | None = None                 # none | mtg | funny | custom | ai
    funny: str | None = None
    dfc: bool | None = None
    prompt: str | None = None
    seed: int | None = None


class DeckPatch(BaseModel):
    name: str | None = None
    profile: str | None = None
    template: str | None = None


class GenerateIn(BaseModel):
    keys: list[str] | None = None
    rewrite_prompts: bool = False
    force: bool = False


class UnitPatch(BaseModel):
    prompt: str | None = None
    seed: int | None = None
    subjects: list[str] | None = None


class ProfileIn(BaseModel):
    name: str = "New style"


class ProfilePatch(BaseModel):
    name: str | None = None
    direction: str | None = None
    lora: str | None = None
    lora_strength: float | None = None
    cartoon_pass: bool | None = None
    cartoon_strength: float | None = None
    cartoon_tags: str | None = None


class SubjectIn(BaseModel):
    name: str = "Person"


class TrainIn(BaseModel):
    steps: int | None = None


class LoraPatch(BaseModel):
    file: str | None = None
    strength: float | None = None


class SubjectPatch(BaseModel):
    name: str | None = None
    tags: list[str] | None = None
    sentence: str | None = None
    count_tag: str | None = None


def _need(x, what="not found"):
    if x is None:
        raise HTTPException(404, what)
    return x


def create_app(engine: Engine | None = None, clerk=None, tunnel_token: str | None = None) -> FastAPI:
    app = FastAPI(title="proxy-forge")
    eng = engine or Engine()
    web_auth.install(app, clerk, tunnel_token)

    @app.get("/app-config.json", include_in_schema=False)
    def page_config():
        issuer = getattr(clerk, "issuer", "") if clerk else ""
        return JSONResponse({"clerk": {"publishableKey": web_auth.clerk_publishable_key(issuer), "frontendApi": issuer} if issuer else None}, headers={"Cache-Control": "no-cache"})

    # ---------------------------------------------------------------------------------------------------------------------------------------------------- status
    @app.get("/api/status")
    def status():
        try:
            info = eng.studio.info(fresh=True)
        except StudioError as e:
            info, problem = None, str(e)
        else:
            problem = None
        picture = (info or {}).get("picture", {})
        train = (info or {}).get("train", {})
        return {"studio": info is not None, "studio_problem": problem, "studio_url": eng.studio.url,
                "comfy": bool(picture.get("ready")), "picture_model": picture.get("model"), "unet": picture.get("unet"),
                "text_model": (info or {}).get("text", {}).get("model"), "vision_model": (info or {}).get("vision", {}).get("model"),
                "printings": eng.prt.count() if eng.prt.ready() else 0, "printings_age_days": round(eng.prt.age() / 86400, 1) if eng.prt.ready() else None, "scryfall_cards": eng.scry.count(), "scryfall_age_days": round((eng.scry.age() or 0) / 86400, 1) if eng.scry.age() is not None else None,
                "loras": [l for l in (info or {}).get("loras", {}).get("files", []) if not l.startswith("pf_")],
                "trainer": bool(train.get("available")), "trainer_problem": problem or train.get("why")}

    @app.get("/api/templates")
    def templates():
        return [{"id": t["id"], "name": t.get("name", t["id"]), "blurb": t.get("blurb", ""), "shape": render.art_shape(t)} for t in render.list_templates()]

    @app.get("/api/templates/{tid}/preview.jpg")
    def template_preview(tid: str):
        try:
            tpl = render.get_template(tid)
        except KeyError:
            raise HTTPException(404, "no such template")
        buf = io.BytesIO()
        render.render(render.sample_unit(), None, tpl, scale=0.48).save(buf, "JPEG", quality=88)
        return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-cache"})

    # --------------------------------------------------------------------------------------------------------------------------------------------------- profiles
    @app.get("/api/profiles")
    def profiles():
        return store.list_profiles()

    @app.post("/api/profiles")
    def profile_new(b: ProfileIn):
        return store.new_profile(b.name)

    @app.get("/api/profiles/{pid}")
    def profile_get(pid: str):
        return _need(store.get_profile(pid))

    @app.patch("/api/profiles/{pid}")
    def profile_patch(pid: str, b: ProfilePatch):
        try:
            return store.update_profile(pid, b.model_dump(exclude_none=True))
        except KeyError:
            raise HTTPException(404, "no such profile")

    @app.delete("/api/profiles/{pid}")
    def profile_delete(pid: str):
        store.delete_profile(pid)
        return {"ok": True}

    @app.post("/api/profiles/{pid}/subjects")
    def subject_new(pid: str, b: SubjectIn):
        try:
            return store.add_subject(pid, b.name)
        except KeyError:
            raise HTTPException(404, "no such profile")

    @app.patch("/api/profiles/{pid}/subjects/{sid}")
    def subject_patch(pid: str, sid: str, b: SubjectPatch):
        try:
            return store.update_subject(pid, sid, b.model_dump(exclude_none=True))
        except KeyError:
            raise HTTPException(404, "no such subject")

    @app.delete("/api/profiles/{pid}/subjects/{sid}")
    def subject_delete(pid: str, sid: str):
        store.delete_subject(pid, sid)
        return {"ok": True}

    @app.post("/api/profiles/{pid}/subjects/{sid}/photos")
    async def photo_add(pid: str, sid: str, files: list[UploadFile] = File(...)):
        added = []
        for f in files:
            try:
                data = await f.read()
                Image.open(io.BytesIO(data)).verify()                           # a real picture, not something renamed
                added.append(store.add_photo(pid, sid, f.filename or "photo.jpg", data))
            except KeyError:
                raise HTTPException(404, "no such subject")
            except Exception as e:
                raise HTTPException(400, f"{f.filename}: {e}")
        return {"added": added}

    @app.get("/api/profiles/{pid}/subjects/{sid}/photos/{name}")
    def photo_get(pid: str, sid: str, name: str):
        p = store.photo_dir(pid, sid) / Path(name).name
        if not p.is_file():
            raise HTTPException(404, "no such photo")
        im = Image.open(p)
        im.thumbnail((320, 320))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=85)
        return Response(buf.getvalue(), media_type="image/jpeg")

    @app.delete("/api/profiles/{pid}/subjects/{sid}/photos/{name}")
    def photo_delete(pid: str, sid: str, name: str):
        store.delete_photo(pid, sid, name)
        return {"ok": True}

    @app.post("/api/profiles/{pid}/subjects/{sid}/train")
    def subject_train(pid: str, sid: str, b: TrainIn):
        p = _need(store.get_profile(pid), "no such profile")
        s = _need(store.get_subject(p, sid), "no such subject")
        try:
            train = eng.studio.info(fresh=True)["train"]
        except StudioError as e:
            raise HTTPException(400, str(e))
        if not train.get("available"):
            raise HTTPException(400, train.get("why") or "the studio cannot train right now")
        if len(s["photos"]) < lora_train.MIN_PHOTOS:
            raise HTTPException(400, f"add at least {lora_train.MIN_PHOTOS} photos first (15 to 30 different ones is better)")
        return eng.train_subject(pid, sid, max(200, min(3000, b.steps)) if b.steps else None).public()

    @app.post("/api/profiles/{pid}/subjects/{sid}/lora/preview")
    def lora_preview(pid: str, sid: str):
        p = _need(store.get_profile(pid), "no such profile")
        s = _need(store.get_subject(p, sid), "no such subject")
        if not s.get("lora"):
            raise HTTPException(400, "train this person's LoRA first")
        return eng.preview_lora(pid, sid).public()

    @app.patch("/api/profiles/{pid}/subjects/{sid}/lora")
    def lora_patch(pid: str, sid: str, b: LoraPatch):
        try:
            return store.update_lora(pid, sid, b.model_dump(exclude_none=True))
        except KeyError:
            raise HTTPException(404, "no trained LoRA for this person")

    @app.delete("/api/profiles/{pid}/subjects/{sid}/lora")
    def lora_delete(pid: str, sid: str):
        store.update_subject(pid, sid, {"lora": None})
        return {"ok": True}

    @app.get("/api/profiles/{pid}/subjects/{sid}/lora/previews/{name}")
    def lora_preview_image(pid: str, sid: str, name: str):
        f = store.preview_dir(pid, sid) / Path(name).name
        if not f.is_file():
            raise HTTPException(404, "no such test picture")
        return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})

    @app.post("/api/profiles/{pid}/subjects/{sid}/describe")
    def subject_describe(pid: str, sid: str):
        p = _need(store.get_profile(pid), "no such profile")
        s = _need(store.get_subject(p, sid), "no such subject")
        return eng.describe_subject(pid, sid).public()

    # ------------------------------------------------------------------------------------------------------------------------------------------------------ decks
    @app.get("/api/decks")
    def decks():
        return store.list_decks()

    @app.post("/api/decks")
    def deck_new(b: DeckIn):
        try:
            render.get_template(b.template)
        except KeyError:
            raise HTTPException(400, "no such template")
        d = store.new_deck(b.name, b.profile, b.template, b.include_sideboard)
        if b.art_policy:
            store.update_deck(d["id"], lambda x: x.update(art_policy={**resolver.DEFAULT_POLICY, **b.art_policy}))
        return {"deck": d["id"], "job": eng.import_deck(d["id"], b.text).public()}

    @app.get("/api/decks/{did}")
    def deck_get(did: str):
        return _need(store.get_deck(did), "no such deck")

    @app.patch("/api/decks/{did}")
    def deck_patch(did: str, b: DeckPatch):
        fields = b.model_dump(exclude_none=True)
        if "template" in fields:
            try:
                render.get_template(fields["template"])
            except KeyError:
                raise HTTPException(400, "no such template")
        try:
            store.update_deck(did, lambda d: d.update(fields))
        except KeyError:
            raise HTTPException(404, "no such deck")
        return {"job": eng.render_deck(did).public()} if "template" in fields else {"ok": True}

    @app.delete("/api/decks/{did}")
    def deck_delete(did: str):
        store.delete_deck(did)
        return {"ok": True}

    @app.post("/api/decks/{did}/generate")
    def deck_generate(did: str, b: GenerateIn):
        _need(store.get_deck(did), "no such deck")
        return eng.generate(did, b.keys, b.rewrite_prompts, b.force).public()

    @app.post("/api/decks/{did}/render")
    def deck_render(did: str):
        _need(store.get_deck(did), "no such deck")
        return eng.render_deck(did).public()

    @app.patch("/api/decks/{did}/units/{key}")
    def unit_patch(did: str, key: str, b: UnitPatch):
        fields = b.model_dump(exclude_none=True)

        def apply(d):
            if key not in d["units"]:
                raise KeyError(key)
            d["units"][key].update(fields)
        try:
            store.update_deck(did, apply)
        except KeyError:
            raise HTTPException(404, "no such card")
        return {"ok": True}

    @app.get("/api/decks/{did}/cards/{key}.png")
    def card_full(did: str, key: str):
        try:
            p = eng.ensure_card(did, key)
        except KeyError:
            raise HTTPException(404, "no such card")
        return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.get("/api/decks/{did}/cards/{key}.jpg")
    def card_small(did: str, key: str):
        try:
            p = eng.ensure_card(did, key, thumb=True)
        except KeyError:
            raise HTTPException(404, "no such card")
        return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})

    @app.get("/api/decks/{did}/art/{key}.png")
    def unit_art(did: str, key: str):
        d = _need(store.get_deck(did), "no such deck")
        u = _need(d["units"].get(key), "no such card")
        if not u.get("art") or not art_path(u["art"]).exists():
            raise HTTPException(404, "no art yet")
        return FileResponse(art_path(u["art"]), media_type="image/png")

    @app.get("/api/decks/{did}/export.pdf")
    def export_pdf(did: str, paper: str = "letter", copies: bool = True, size: str = "mtg", margin: float = 5.0, gap: float = 0.0, turn: str = "auto", marks: bool = True, skip_basics: bool = False,
                   duplex: str = "none", flip: str = "long", part: str = "all", reverse_backs: bool = False, back_dx: float = 0.0, back_dy: float = 0.0):
        d = _need(store.get_deck(did), "no such deck")
        if paper not in export.PAPER or size not in export.CARD_MM or turn not in ("auto", "never", "always") or not 0 <= margin <= 30 or not 0 <= gap <= 20:
            raise HTTPException(400, "bad print options")
        if duplex not in ("none", "auto", "manual") or flip not in export.FLIPS or part not in ("all", "fronts", "backs") or not -5 <= back_dx <= 5 or not -5 <= back_dy <= 5:
            raise HTTPException(400, "bad two-sided options")
        name = safe(d["name"])
        if duplex != "none":
            pairs = eng.print_pairs(did, copies, skip_basics, duplex=True)
            if not pairs:
                raise HTTPException(400, "no cards")
            if not any(b for _, b in pairs):
                raise HTTPException(400, "this deck has no back yet: choose one in the Source step (Card backs)")
            try:
                f, b = export.duplex_pages(pairs, paper, size, margin, gap, turn, marks, flip, back_dx, back_dy)
                pdf = export.pages_pdf(export.duplex_order(f, b, duplex, part, reverse_backs))
            except ValueError as e:
                raise HTTPException(400, str(e))
            tag = f"-{duplex}" + (f"-{part}" if duplex == "manual" and part != "all" else "")
            return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}-{paper}{tag}.pdf"'})
        imgs = [p for _, p in eng.card_images(did, copies, skip_basics)]
        if not imgs:
            raise HTTPException(400, "no cards")
        try:
            pdf = export.pdf_bytes(imgs, paper, size=size, margin_mm=margin, gap_mm=gap, turn=turn, marks=marks)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}-{paper}.pdf"'})

    @app.get("/api/duplex-test.pdf")
    def duplex_test(paper: str = "letter", size: str = "mtg", flip: str = "long", turn: str = "auto", margin: float = 5.0, back_dx: float = 0.0, back_dy: float = 0.0):
        """Two pages for checking a printer: print both sides, hold it to the light."""
        if paper not in export.PAPER or flip not in export.FLIPS or turn not in ("auto", "never", "always") or size not in export.CARD_MM:
            raise HTTPException(400, "bad options")
        return Response(export.pages_pdf(export.test_sheets(paper, size, margin, turn, flip, back_dx, back_dy)), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="duplex-test-{paper}-{flip}.pdf"'})

    # ----------------------------------------------------------------------------------------------------------------------------------------------------------- card backs
    @app.get("/api/backs")
    def back_list():
        return [{"id": "mtg", "name": "Magic card back", "blurb": "The official back, from Scryfall."}, *backs.FUNNY]

    @app.get("/api/backs/{bid}.jpg")
    def back_preview(bid: str):
        try:
            im = backs.official(eng.scan_transport) if bid == "mtg" else backs.funny(bid)
        except KeyError:
            raise HTTPException(404, "no such back")
        except Exception as e:
            raise HTTPException(502, str(e))
        buf = io.BytesIO()
        im.resize((250, 350), Image.LANCZOS).save(buf, "JPEG", quality=88)
        return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})

    @app.put("/api/decks/{did}/back")
    def deck_back(did: str, b: BackIn):
        d = _need(store.get_deck(did), "no such deck")
        f = b.model_dump(exclude_none=True)
        if f.get("mode") not in (None, "none", "mtg", "funny", "custom", "ai"):
            raise HTTPException(400, "mode must be none, mtg, funny, custom or ai")
        if f.get("funny") and f["funny"] not in {x["id"] for x in backs.FUNNY}:
            raise HTTPException(400, "no such funny back")
        if f.get("mode") == "custom" and not (store.deck_dir(did) / "back-custom.png").exists():
            raise HTTPException(400, "upload a picture for the back first")
        if f.get("mode") == "ai" and not eng.back_cfg(d)["art"]:
            raise HTTPException(400, "draw the AI back first (Draw an AI back)")
        return {"job": eng.set_back(did, f).public()}

    @app.post("/api/decks/{did}/back/draw")
    def deck_back_draw(did: str, b: BackIn):
        _need(store.get_deck(did), "no such deck")
        if b.seed is not None:
            store.update_deck(did, lambda d: d.update(back={**eng.back_cfg(d), "seed": b.seed}))
        return {"job": eng.draw_back(did, b.prompt).public()}

    @app.post("/api/decks/{did}/back/custom")
    async def deck_back_custom(did: str, file: UploadFile = File(...)):
        _need(store.get_deck(did), "no such deck")
        try:
            im = Image.open(io.BytesIO(await file.read()))
            im.load()
        except Exception:
            raise HTTPException(400, "that is not a picture I can read")
        out = store.deck_dir(did) / "back-custom.png"
        backs.cover(im).save(out, "PNG")
        return {"job": eng.set_back(did, {"mode": "custom"}).public()}

    @app.get("/api/decks/{did}/back.jpg")
    def deck_back_image(did: str):
        _need(store.get_deck(did), "no such deck")
        p = eng.back_path(did)
        if not p.exists():
            raise HTTPException(404, "no back")
        buf = io.BytesIO()
        with Image.open(p) as im:
            im.convert("RGB").resize((360, 504), Image.LANCZOS).save(buf, "JPEG", quality=88)
        return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-cache"})

    @app.get("/api/decks/{did}/export.zip")
    def export_zip(did: str, copies: bool = False, bleed: bool = False):
        d = _need(store.get_deck(did), "no such deck")
        if bleed:
            from .engine import print_shop_images
            return Response(export.zip_images(print_shop_images(eng, did, copies)), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{safe(d["name"])}-print-shop.zip"'})
        return Response(export.zip_bytes(eng.card_images(did, copies)), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{safe(d["name"])}.zip"'})

    # -------------------------------------------------------------------------------------------------------------------------------------------------------- jobs
    @app.get("/api/jobs")
    def jobs():
        return [j.public() for j in sorted(eng.jobs.values(), key=lambda j: -j.created)[:20]]

    @app.get("/api/jobs/{jid}")
    def job_get(jid: str):
        return _need(eng.jobs.get(jid), "no such job").public()

    @app.post("/api/jobs/{jid}/cancel")
    def job_cancel(jid: str):
        _need(eng.jobs.get(jid), "no such job").cancel = True
        return {"ok": True}

    # --------------------------------------------------------------------------------------------------------------------------------------- official art: sets, printings
    def _index():
        if not eng.prt.ready():
            raise HTTPException(409, "The printings index is not built yet (POST /api/index).")
        return eng.prt

    @app.post("/api/index")
    def index_build():
        return eng.submit("index", None, lambda job: eng.prt.build(lambda m: setattr(job, "msg", m)), queue="net").public()

    @app.get("/api/sets")
    def sets(q: str = "", type: str = ""):
        return [{"code": s["code"], "name": s["name"], "set_type": s["set_type"], "released_at": s["released_at"], "card_count": s["card_count"], "parent": s["parent"]}
                for s in _index().sets(q, type)]

    @app.get("/api/sets/{code}/icon.svg")
    def set_icon(code: str):
        code = safe(code)
        f = config.folder("scryfall", "icons") / f"{code}.svg"
        if not f.exists():
            with _index()._db() as db:
                row = db.execute("select icon_uri from sets where code=?", (code,)).fetchone()
            if not row or not row[0]:
                raise HTTPException(404, "no such set")
            import httpx
            r = httpx.get(row[0], headers={"User-Agent": config.SCRYFALL_UA}, timeout=20, follow_redirects=True)
            r.raise_for_status()
            f.write_bytes(r.content)
        return FileResponse(f, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/api/decks/{did}/coverage")
    def coverage(did: str):
        d = _need(store.get_deck(did), "no such deck")
        pr = _index()
        bases = list(dict.fromkeys(d["units"][k].get("split_of", k) for k in d["order"]))
        oids = [o for o in (resolver.oracle_of(pr, d["units"][b]) for b in bases) if o]
        cov = pr.coverage(oids)
        info = {s["code"]: s for s in pr.sets()}
        return {"total": len(set(oids)), "sets": [{"code": c, "name": info[c]["name"], "set_type": info[c]["set_type"], "released_at": info[c]["released_at"], "have": n}
                                                  for c, n in cov.items() if c in info]}

    @app.put("/api/decks/{did}/art-policy")
    def art_policy(did: str, b: ArtPolicyIn):
        _need(store.get_deck(did), "no such deck")
        pol = {**resolver.DEFAULT_POLICY, **b.model_dump(exclude_none=True)}
        if pol["source"] not in ("forge", "archive", "vault", "budget"):
            raise HTTPException(400, "source must be forge, archive, vault or budget")
        if pol["source"] == "archive" and not pol["sets"] and not pol["pins"]:
            raise HTTPException(400, "pick at least one set for Archive (or honor the sets stated in the deck list)")
        if pol["print"] not in ("scan", "template"):
            raise HTTPException(400, "print must be scan or template")
        return {"job": eng.apply_policy(did, pol).public()}

    @app.get("/api/decks/{did}/units/{key}/printings")
    def unit_printings(did: str, key: str):
        d = _need(store.get_deck(did), "no such deck")
        u = _need(d["units"].get(key), "no such card")
        pr = _index()
        oid = resolver.oracle_of(pr, u)
        if oid is None:
            return {"variants": []}
        pol = resolver.policy_of(d)
        cur = (u.get("printing") or {}).get("id")
        out = []
        if u.get("is_token"):                                                  # every token of this name, in every set: they are different cards, and cost nothing
            for v in pr.token_variants(u["name"]):
                out.append({"treatment": v["treatment"], "illustration_id": v["illustration_id"], "amount": None, "finish": None, "current": any(p["id"] == cur for p in v["printings"]),
                            "best": v["best"]["id"], "printings": [{"id": p["id"], "set": p["set_code"], "cn": p["cn"], "released": p["released_at"], "status": p["image_status"],
                                                                    "current": p["id"] == cur} for p in v["printings"]]})
            return {"currency": pol["vault"]["currency"], "variants": out}
        for v in vault.appraise(pr, oid, {**pol, "source": "vault"}):
            ps = [p for p in pr.variants(oid) if p["treatment"] == v["treatment"] and p["illustration_id"] == v["illustration_id"]]
            allp = ps[0]["printings"] if ps else [v["printing"]]
            out.append({"treatment": v["treatment"], "illustration_id": v["illustration_id"], "amount": v["amount"], "finish": v["finish"], "current": any(p["id"] == cur for p in allp),
                        "best": v["printing"]["id"], "printings": [{"id": p["id"], "set": p["set_code"], "cn": p["cn"], "released": p["released_at"], "status": p["image_status"],
                                                                    "current": p["id"] == cur} for p in allp]})
        return {"currency": pol["vault"]["currency"], "variants": out}

    @app.put("/api/decks/{did}/units/{key}/printing")
    def unit_printing(did: str, key: str, b: PrintingIn):
        d = _need(store.get_deck(did), "no such deck")
        _need(d["units"].get(key), "no such card")
        _index()
        return {"job": eng.set_printing(did, key, b.printing_id).public()}

    @app.get("/api/decks/{did}/appraisal")
    def appraisal(did: str):
        d = _need(store.get_deck(did), "no such deck")
        cur = resolver.policy_of(d)["vault"]["currency"]
        rows = [(d["units"][k], d["units"][k].get("price")) for k in d["order"] if d["units"][k].get("price")]
        top = sorted(({"name": u["name"], "amount": p["amount"], "copies": u["copies"], "key": k} for k, u, p in ((k, d["units"][k], d["units"][k]["price"]) for k in d["order"]
                                                                                                               if d["units"][k].get("price"))), key=lambda r: -r["amount"] * r["copies"])[:10]
        return {"currency": cur, "total": round(sum(p["amount"] * u["copies"] for u, p in rows), 2), "priced": len(rows), "cards": len(d["order"]),
                "as_of": next((p["as_of"] for _, p in rows), ""), "top": top}

    @app.get("/api/scans/{pid}/{face}.jpg")
    def scan_thumb(pid: str, face: int):
        _index()
        try:
            p = eng._printing_row(pid)
            return FileResponse(scans.fetch(p, face, "normal", eng.scan_transport), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
        except Exception as e:
            raise HTTPException(404, str(e))

    @app.post("/api/import")
    async def import_deck_text(file: UploadFile | None = File(None), url: str = Form("")):
        """A file (.txt, .dek, .csv, MTGA) or an Archidekt link, turned into deck-list text."""
        try:
            if file is not None:
                text, warnings = importers.from_file(file.filename or "", await file.read())
                return {"text": text, "source": file.filename, "warnings": warnings}
            if url.strip():
                text, warnings = importers.from_archidekt(url.strip())
                return {"text": text, "source": "Archidekt", "warnings": warnings}
        except importers.ImportError_ as e:
            raise HTTPException(400, str(e))
        raise HTTPException(400, "give a file or a link")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def page():
        # the script and stylesheet carry the time of the last change in their URL: a new URL is never answered from an old copy kept by the browser or Cloudflare's edge
        v = str(int(max(p.stat().st_mtime for p in WEB_DIR.rglob("*") if p.is_file())))
        return Response((WEB_DIR / "index.html").read_text(encoding="utf-8").replace("{{v}}", v), media_type="text/html", headers={"Cache-Control": "no-store"})

    app.mount("/app", NoStoreStatic(directory=str(WEB_DIR)), name="web")
    return app


def main() -> None:
    import uvicorn

    from pathlib import Path as _P
    token_file = _P(os.environ.get("PROXY_TUNNEL_TOKEN_FILE", str(_P(__file__).resolve().parents[1] / "tunnel-token.txt")))
    tunnel_token = token_file.read_text(encoding="utf-8").strip() if token_file.is_file() else None
    clerk = web_auth.clerk_from_env("PROXY")
    if clerk and not (clerk.users or clerk.emails):
        print("WARNING: a Clerk issuer is set but no user is allowed (STUDIO_CLERK_USERS): every sign-in will be refused.", flush=True)
    host = os.environ.get("PROXY_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost", "::1") and os.environ.get("PROXY_NO_AUTH", "").strip() != "1":
        raise SystemExit("PROXY_HOST is not loopback and there is no sign-in yet: refusing to serve (PROXY_NO_AUTH=1 only on a network you trust).")
    uvicorn.run(create_app(clerk=clerk, tunnel_token=tunnel_token), host=host, port=int(os.environ.get("PROXY_PORT", "7870")))


if __name__ == "__main__":
    main()
