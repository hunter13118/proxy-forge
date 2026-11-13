"""The web app: a small JSON API over the engine, and the page (web/). Loopback only unless PROXY_NO_AUTH=1 says the network is trusted; tunnel sign-in is a later step."""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel
from studio_kit import web_auth

from . import export, lora_train, render, store
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
                "scryfall_cards": eng.scry.count(), "scryfall_age_days": round((eng.scry.age() or 0) / 86400, 1) if eng.scry.age() is not None else None,
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
    def export_pdf(did: str, paper: str = "letter", copies: bool = True, size: str = "mtg", margin: float = 5.0, gap: float = 0.0, turn: str = "auto", marks: bool = True, skip_basics: bool = False):
        d = _need(store.get_deck(did), "no such deck")
        if paper not in export.PAPER or size not in export.CARD_MM or turn not in ("auto", "never", "always") or not 0 <= margin <= 30 or not 0 <= gap <= 20:
            raise HTTPException(400, "bad print options")
        imgs = [p for _, p in eng.card_images(did, copies, skip_basics)]
        if not imgs:
            raise HTTPException(400, "no cards")
        try:
            pdf = export.pdf_bytes(imgs, paper, size=size, margin_mm=margin, gap_mm=gap, turn=turn, marks=marks)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{safe(d["name"])}-{paper}.pdf"'})

    @app.get("/api/decks/{did}/export.zip")
    def export_zip(did: str, copies: bool = False):
        d = _need(store.get_deck(did), "no such deck")
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

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def page():
        # the script and stylesheet carry the time of the last change in their URL: a new URL is never answered from an old copy kept by the browser or Cloudflare's edge
        v = str(int(max(p.stat().st_mtime for p in WEB_DIR.iterdir() if p.is_file())))
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
