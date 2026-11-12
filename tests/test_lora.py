from proxy_forge import lora_train, prompts, store
from proxy_forge.studio import Studio


def test_trigger_is_stable_and_not_a_name():
    a, b = lora_train.make_trigger("sam-abc12"), lora_train.make_trigger("sam-abc12")
    assert a == b and a.isalpha() and 6 <= len(a) <= 8 and lora_train.make_trigger("jo-xyz") != a


def test_epochs_aim_for_the_step_target():
    assert lora_train.epochs_for(20, 1000) == 50
    assert lora_train.epochs_for(500, 1000) == 8                       # never fewer than 8
    assert lora_train.epochs_for(3, 1000) == 100                       # never more than 100


def test_a_lora_is_named_after_its_subject_in_the_studios_alphabet():
    assert lora_train.lora_name({"id": "Garry-dd126"}) == "pf_garry_dd126"
    assert len(lora_train.lora_name({"id": "x" * 200})) <= 60


def test_triggers_go_in_after_the_quality_words_once():
    subs = [{"lora": {"trigger": "kofa"}}, {"lora": None}]
    p = prompts.with_triggers("masterpiece, best quality, 1boy, forest. A scene.", subs)
    assert p.startswith("masterpiece, best quality, kofa, illustration, 1boy")
    assert prompts.with_triggers(p, subs) == p                         # not twice
    assert prompts.with_triggers("anything", [{"lora": None}]) == "anything"


def test_lora_choice_and_strength_are_validated(tmp_path, monkeypatch):
    from proxy_forge import config
    monkeypatch.setattr(config, "DATA", tmp_path)
    p = store.new_profile("t")
    s = store.add_subject(p["id"], "A")
    store.update_subject(p["id"], s["id"], {"lora": {"checkpoints": ["a.safetensors", "b.safetensors"], "file": "a.safetensors", "strength": 0.8}})
    r = store.update_lora(p["id"], s["id"], {"file": "b.safetensors", "strength": 9})
    assert r["file"] == "b.safetensors" and r["strength"] == 1.5
    assert store.update_lora(p["id"], s["id"], {"file": "evil.safetensors"})["file"] == "b.safetensors"


class FakeStudio:
    url = "http://studio.invalid"

    def info(self, fresh=False):
        return {"picture": {"model": "anima-turbo", "unet": "anima-turbo-v1.1.safetensors", "steps": 10, "cfg": 1.0, "ready": True}}


def test_cartoon_pass_only_with_person_loras_and_restyle_request():
    from proxy_forge import config
    from proxy_forge.engine import Engine
    eng = Engine(studio=FakeStudio(), start=False)
    unit = {"prompt": "masterpiece, best quality, 1boy, forest", "seed": 5}
    sub = [{"lora": {"file": "pf_x-final.safetensors", "strength": 0.8, "trigger": "kofa"}}]
    on = eng.graph_params(unit, {"lora": "style.safetensors", "cartoon_pass": True, "cartoon_strength": 0.45}, 832, 1216, sub)
    assert on["steps"] == 10 and on["cfg"] == 1.0 and on["unet"] == "anima-turbo-v1.1.safetensors"          # the studio's picture model sets these
    assert on["restyle_denoise"] == 0.45 and "kofa" not in on["restyle_positive"] and "kofa" in on["positive"] and config.CARTOON_TAGS.split(",")[0] in on["positive"]
    assert "restyle_denoise" not in eng.graph_params(unit, {"lora": "", "cartoon_pass": False}, 832, 1216, sub)
    assert "restyle_denoise" not in eng.graph_params(unit, {"lora": ""}, 832, 1216, [])               # nobody with a LoRA in the picture: nothing to correct
    body = Studio.image_request(on)                                                                    # what the studio is asked: the style LoRA stays in the restyle pass, the person's does not
    assert body["loras"] == [{"file": "style.safetensors", "strength": 0.8, "restyle": True}, {"file": "pf_x-final.safetensors", "strength": 0.8, "restyle": False}]
    assert body["restyle"] == {"prompt": on["restyle_positive"], "denoise": 0.45} and body["app"] == "proxy-forge"
    plain = Studio.image_request(eng.graph_params(unit, {"lora": ""}, 832, 1216, []))
    assert plain["loras"] == [] and "restyle" not in plain


def test_art_already_drawn_is_not_drawn_again(tmp_path, monkeypatch):
    from proxy_forge import config
    from proxy_forge.engine import Engine
    from PIL import Image
    monkeypatch.setattr(config, "DATA", tmp_path)
    drawn = []

    class Drawing(FakeStudio):
        def draw(self, params, cancelled=lambda: False):
            drawn.append(params)
            return Image.new("RGB", (8, 8), "red")
    eng = Engine(studio=Drawing(), start=False)
    unit = {"prompt": "masterpiece, best quality, forest", "seed": 5}
    job = type("J", (), {"cancel": False})()
    a = eng._draw(job, unit, {"lora": ""}, 832, 1216, False, [])
    b = eng._draw(job, unit, {"lora": ""}, 832, 1216, False, [])
    assert a == b and len(drawn) == 1
    eng._draw(job, unit, {"lora": ""}, 832, 1216, True, [])                                          # forced
    assert len(drawn) == 2
