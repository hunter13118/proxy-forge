"""proxy-forge as a client of the studio's /v1/ai API (studio.py), with the studio faked."""
import io

import httpx
import pytest
from PIL import Image

from proxy_forge import lora_train, studio as studio_mod
from proxy_forge.studio import Cancelled, Studio, StudioError


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 48), "#445566").save(buf, "PNG")
    return buf.getvalue()


class FakeStudioServer:
    """Answers httpx.request the way the studio's /v1/ai would."""

    def __init__(self, monkeypatch, states=("running", "done")):
        self.calls, self.states, self.polls = [], list(states), 0
        monkeypatch.setattr(studio_mod.httpx, "request", self.request)

    def request(self, method, url, headers=None, timeout=None, **kw):
        path = url.split("//", 1)[1].split("/", 1)[1]
        self.calls.append((method, "/" + path, kw))
        req = httpx.Request(method, url)
        if path == "v1/ai/images":
            return httpx.Response(202, json={"id": "j1", "state": "queued"}, request=req)
        if path == "v1/ai/lora-trainings":
            return httpx.Response(202, json={"id": "t1", "state": "queued"}, request=req)
        if path.startswith("v1/ai/jobs/") and path.endswith("/image"):
            return httpx.Response(200, content=png_bytes(), request=req)
        if path.startswith("v1/ai/jobs/") and method == "GET":
            state = self.states[min(self.polls, len(self.states) - 1)]
            self.polls += 1
            body = {"id": path.split("/")[3], "state": state, "message": "training", "done": 40, "total": 100, "error": "",
                    "result": {"name": "pf_amy", "trigger": "kofa", "checkpoints": ["a", "b"], "file": "b", "images": 6, "epochs": 20}}
            return httpx.Response(200, json=body, request=req)
        if path.startswith("v1/ai/jobs/") and method == "DELETE":
            return httpx.Response(200, json={}, request=req)
        if path == "v1/ai/text":
            return httpx.Response(200, json={"model": "m", "text": "{}", "json": {"scene": "a fox", "tags": ["fox"]}}, request=req)
        if path.startswith("v1/ai/datasets"):
            return httpx.Response(200 if method != "PUT" else 201, json={"ok": True}, request=req)
        if path == "v1/ai":
            return httpx.Response(200, json={"picture": {"ready": True, "model": "anima-turbo"}}, request=req)
        return httpx.Response(404, json={"detail": {"message": "no"}}, request=req)


def test_a_drawing_is_requested_followed_and_fetched(monkeypatch):
    server = FakeStudioServer(monkeypatch)
    monkeypatch.setattr(studio_mod.time, "sleep", lambda s: None)
    img = Studio("http://studio.invalid").draw({"positive": "p", "negative": "n", "width": 832, "height": 1216, "seed": 3, "steps": 10, "cfg": 1.0, "lora": "", "extra_loras": []})
    assert img.size == (32, 48)
    post = next(c for c in server.calls if c[0] == "POST")
    assert post[1] == "/v1/ai/images" and post[2]["json"]["prompt"] == "p" and post[2]["json"]["seed"] == 3


def test_cancelling_a_drawing_cancels_it_in_the_studio(monkeypatch):
    server = FakeStudioServer(monkeypatch, states=("running", "cancelled"))
    monkeypatch.setattr(studio_mod.time, "sleep", lambda s: None)
    with pytest.raises(Cancelled):
        Studio("http://studio.invalid").draw({"positive": "p", "negative": "", "width": 64, "height": 64, "seed": 1}, cancelled=lambda: True)
    assert any(c[0] == "DELETE" and c[1] == "/v1/ai/jobs/j1" for c in server.calls)


def test_a_failed_studio_job_raises_its_reason(monkeypatch):
    class Failing(FakeStudioServer):
        def request(self, method, url, **kw):
            r = super().request(method, url, **kw)
            if method == "GET" and "/jobs/" in url and not url.endswith("/image"):
                return httpx.Response(200, json={"id": "j1", "state": "error", "error": "ComfyUI failed: out of memory", "message": ""}, request=httpx.Request(method, url))
            return r
    Failing(monkeypatch)
    monkeypatch.setattr(studio_mod.time, "sleep", lambda s: None)
    with pytest.raises(StudioError, match="out of memory"):
        Studio("http://studio.invalid").draw({"positive": "p", "negative": "", "width": 64, "height": 64, "seed": 1})


def test_the_studio_being_down_is_explained(monkeypatch):
    def refuse(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(studio_mod.httpx, "request", refuse)
    s = Studio("http://studio.invalid")
    assert "not answering" in s.reachable() and "start-studio" in s.reachable()
    assert s.lora_files() == []


def test_words_come_back_parsed(monkeypatch):
    server = FakeStudioServer(monkeypatch)
    out = Studio("http://studio.invalid").chat_json("a card", system="s", temperature=0.8)
    assert out == {"scene": "a fox", "tags": ["fox"]}
    body = server.calls[0][2]["json"]
    assert body["json_mode"] is True and body["system"] == "s" and "keep_alive" not in body            # the studio decides how long its model stays loaded


def test_a_token_is_sent_when_there_is_one(monkeypatch):
    seen = {}

    def grab(method, url, headers=None, **kw):
        seen.update(headers or {})
        return httpx.Response(200, json={"picture": {"ready": True}}, request=httpx.Request(method, url))
    monkeypatch.setattr(studio_mod.httpx, "request", grab)
    Studio("http://studio.invalid", token="s3cret").info()
    assert seen["Authorization"] == "Bearer s3cret"


def test_training_sends_the_photos_then_follows_the_job(monkeypatch, tmp_path):
    server = FakeStudioServer(monkeypatch, states=("running", "running", "done"))
    monkeypatch.setattr(studio_mod.time, "sleep", lambda s: None)
    photos = []
    for i in range(6):
        p = tmp_path / f"{i}.png"
        p.write_bytes(png_bytes())
        photos.append(p)

    class Job:
        cancel, msg, done, total = False, "", 0, 0
    job = Job()
    rec = lora_train.train(job, Studio("http://studio.invalid"), {"id": "amy-1", "count_tag": "1girl"}, photos, 400)
    puts = [c for c in server.calls if c[0] == "PUT"]
    assert len(puts) == 6 and puts[0][1] == "/v1/ai/datasets/pf_amy_1/photos/000.jpg"
    start = next(c for c in server.calls if c[1] == "/v1/ai/lora-trainings")[2]["json"]
    assert start["name"] == "pf_amy_1" and start["count_tag"] == "1girl" and start["steps"] == 400 and start["trigger"] == lora_train.make_trigger("amy-1")
    assert rec["file"] == "b" and rec["checkpoints"] == ["a", "b"] and job.done == 40 and job.msg == "training"


def test_too_few_photos_never_reach_the_studio(monkeypatch, tmp_path):
    server = FakeStudioServer(monkeypatch)
    with pytest.raises(RuntimeError, match="at least 6"):
        lora_train.train(type("J", (), {"cancel": False})(), Studio("http://studio.invalid"), {"id": "a"}, [tmp_path / "x.png"], 400)
    assert server.calls == []
