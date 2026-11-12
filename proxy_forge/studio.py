"""
The studio, as proxy-forge uses it. Everything that needs a model goes through the studio's /v1/ai API (ebook-av-service docs/AI-API.md): words from its language and vision models,
pictures from its ComfyUI, and LoRAs from its trainer. Proxy-forge keeps what is its own (cards, prompts, templates, profiles, the people and their photos), and the studio keeps
the GPU, the models and the care for sharing them with whatever else is using it.
"""
from __future__ import annotations

import io
import logging
import time
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from . import config

log = logging.getLogger("studio")


class StudioError(RuntimeError):
    pass


class Cancelled(StudioError):
    pass


def _why(r: httpx.Response) -> str:
    try:
        d = r.json().get("detail", r.json())
        return str(d.get("message") or d.get("error") or d) if isinstance(d, dict) else str(d)
    except Exception:
        return r.text[:300] or f"HTTP {r.status_code}"


class Studio:
    def __init__(self, url: str | None = None, token: str | None = None):
        self.url = (url or config.STUDIO_URL).rstrip("/")
        self.headers = {"Authorization": f"Bearer {token or config.STUDIO_TOKEN}"} if (token or config.STUDIO_TOKEN) else {}
        self._info: tuple[float, dict] | None = None

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------ plumbing
    def _call(self, method: str, path: str, *, timeout: float = 30, **kw) -> httpx.Response:
        try:
            r = httpx.request(method, f"{self.url}{path}", headers=self.headers, timeout=timeout, **kw)
        except httpx.HTTPError as e:
            raise StudioError(f"the studio at {self.url} is not answering ({type(e).__name__}); start it with D:\\studio-home\\start-studio.ps1") from e
        if r.status_code == 404 and path.startswith("/v1/ai") and "no_such_job" not in r.text:
            raise StudioError(f"the studio at {self.url} has no /v1/ai API: it needs the version that serves other apps")
        if r.status_code >= 400:
            raise StudioError(_why(r))
        return r

    def info(self, fresh: bool = False) -> dict:
        """What the studio can do right now (GET /v1/ai); kept for 10 s so a page that asks often does not hammer it."""
        if fresh or self._info is None or time.time() - self._info[0] > 10:
            self._info = (time.time(), self._call("GET", "/v1/ai", timeout=8).json())
        return self._info[1]

    def reachable(self) -> str | None:
        """None when the studio can draw, else why not."""
        try:
            i = self.info(fresh=True)
        except StudioError as e:
            return str(e)
        return None if i["picture"].get("ready") else "the studio is up but ComfyUI is not answering (its picture model is " + i["picture"].get("model", "?") + ")"

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------------ words
    def chat(self, prompt: str, *, system: str = "", images: list[str] | None = None, json_mode: bool = False, temperature: float = 0.3, keep_alive: str | None = None,
             timeout: float = 240) -> dict:
        """One answer from the studio's language model (or its vision model when `images` are given, as base64). With `json_mode` the parsed object is under "json"."""
        body = {"prompt": prompt, "system": system, "images": images or [], "json_mode": json_mode, "temperature": temperature, "timeout": timeout}
        if keep_alive is not None:
            body["keep_alive"] = keep_alive
        return self._call("POST", "/v1/ai/text", json=body, timeout=timeout + 15).json()

    def chat_json(self, prompt: str, **kw) -> dict:
        return self.chat(prompt, json_mode=True, **kw)["json"]

    # --------------------------------------------------------------------------------------------------------------------------------------------------------------- pictures
    @staticmethod
    def image_request(params: dict) -> dict:
        """proxy-forge's own description of a drawing (engine.graph_params) as the studio's request: the style LoRA first (kept in the restyle pass), then the people's."""
        loras = ([{"file": params["lora"], "strength": float(params.get("lora_strength", 0.8)), "restyle": True}] if params.get("lora") else [])
        loras += [{"file": f, "strength": float(st), "restyle": False} for f, st in params.get("extra_loras", [])]
        body = {"prompt": params["positive"], "negative": params["negative"], "width": params["width"], "height": params["height"], "seed": int(params["seed"]),
                "steps": params.get("steps"), "cfg": params.get("cfg"), "loras": loras, "app": "proxy-forge"}
        if float(params.get("restyle_denoise") or 0) > 0:
            body["restyle"] = {"prompt": params.get("restyle_positive", ""), "denoise": float(params["restyle_denoise"])}
        return body

    def wait(self, job_id: str, cancelled=lambda: False, progress=None, timeout: float = 3600 * 3, every: float = 0.6) -> dict:
        """Follows a studio job until it ends; cancelling here cancels it there."""
        end = time.time() + timeout
        sent = False
        while time.time() < end:
            if cancelled() and not sent:
                sent = True
                try:
                    self._call("DELETE", f"/v1/ai/jobs/{job_id}")
                except StudioError:
                    pass
            try:
                j = self._call("GET", f"/v1/ai/jobs/{job_id}").json()
            except StudioError as e:
                raise StudioError(f"lost track of the studio's job {job_id}: {e}") from e
            if progress:
                progress(j)
            if j["state"] in ("done", "error", "cancelled"):
                if j["state"] == "cancelled" or cancelled():
                    raise Cancelled("cancelled")
                if j["state"] == "error":
                    raise StudioError(j.get("error") or j.get("message") or "the studio failed")
                return j
            time.sleep(every)
        raise StudioError("the studio took too long")

    def draw(self, params: dict, cancelled=lambda: False) -> Image.Image:
        job = self._call("POST", "/v1/ai/images", json=self.image_request(params)).json()
        self.wait(job["id"], cancelled)
        r = self._call("GET", f"/v1/ai/jobs/{job['id']}/image", timeout=60)
        return Image.open(io.BytesIO(r.content)).convert("RGB")

    # --------------------------------------------------------------------------------------------------------------------------------------------------------------------- LoRAs
    def train(self, job, *, name: str, photos: list[Path], count_tag: str, trigger: str, steps: int) -> dict:
        """Sends the photos, has the studio train `name` on them and follows it. `job` is proxy-forge's (cancel, msg, done, total). Returns the studio's record of the LoRA."""
        dataset = name
        self._call("DELETE", f"/v1/ai/datasets/{dataset}")
        job.msg = "sending the photos to the studio"
        for i, p in enumerate(photos):
            if job.cancel:
                self._call("DELETE", f"/v1/ai/datasets/{dataset}")
                raise Cancelled("cancelled")
            try:
                im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
            except Exception as e:
                log.warning("skipping unreadable photo %s: %s", p, e)
                continue
            im.thumbnail((2048, 2048))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=95)
            self._call("PUT", f"/v1/ai/datasets/{dataset}/photos/{i:03d}.jpg", content=buf.getvalue(), timeout=120)
        started = self._call("POST", "/v1/ai/lora-trainings", json={"name": name, "dataset": dataset, "count_tag": count_tag, "trigger": trigger, "steps": steps, "app": "proxy-forge"}).json()

        def mirror(j: dict) -> None:
            job.msg, job.done, job.total = j.get("message") or job.msg, j.get("done", 0), j.get("total", 0)
        done = self.wait(started["id"], cancelled=lambda: job.cancel, progress=mirror, every=3)
        return done["result"]

    def lora_files(self) -> list[str]:
        try:
            return list(self.info()["loras"]["files"])
        except (StudioError, KeyError):
            return []

