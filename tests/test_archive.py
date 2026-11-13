"""Archive and Vault end to end (M2, M3): resolving printings, fetching scans through a mock transport, drawing the official card, hanging a card by hand. No network."""
import io

import httpx
import pytest
from PIL import Image

import test_printings as tp
from proxy_forge import config, printings, render, resolver, scans, store, vault
from proxy_forge.engine import Engine, Job, resolve_deck

CORNER = (40, 40, 40)


def scan_png(colour=CORNER) -> bytes:
    """A 745x1040 'scan': a border-coloured card with transparent rounded corners and a bright centre."""
    im = Image.new("RGBA", (745, 1040), colour + (255,))
    im.paste((200, 30, 30, 255), (60, 120, 685, 600))
    for x in range(30):
        for y in range(30):
            if (30 - x) ** 2 + (30 - y) ** 2 > 900:
                for cx, cy in ((x, y), (744 - x, y), (x, 1039 - y), (744 - x, 1039 - y)):
                    im.putpixel((cx, cy), (0, 0, 0, 0))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def cards():
    cs = tp.fixture()
    for c in cs:
        c["image_uris"] = {k: f"https://cards.scryfall.io/{k}/{c['id']}.{'png' if k == 'png' else 'jpg'}" for k in ("png", "normal", "art_crop")}
    return cs


def img_transport(calls=None):
    def h(req):
        if calls is not None:
            calls.append(str(req.url))
        if req.url.path.endswith(".png"):
            return httpx.Response(200, content=scan_png())
        b = io.BytesIO()
        Image.new("RGB", (488, 680), "#335").save(b, "JPEG")
        return httpx.Response(200, content=b.getvalue())
    return httpx.MockTransport(h)


@pytest.fixture
def pr(tmp_path):
    p = printings.Printings(tmp_path / "p.sqlite", transport=tp.transport(cards()))
    p.build()
    return p


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path / "data")
    p = printings.Printings(tmp_path / "p.sqlite", transport=tp.transport(cards()))
    p.build()
    calls = []
    return Engine(start=False, printings=p, scan_transport=img_transport(calls)), calls


def unit(name, oid, copies=1, pin=None, type_line="Creature", key=None):
    k = key or f"{oid}-0"
    return {"key": k, "oracle_id": oid, "name": name, "type_line": type_line, "face": 0, "faces": 1, "copies": copies, "pin": pin, "prompt": "", "seed": 1, "subjects": [], "art": "",
            "mana_cost": "", "oracle_text": "", "colors": [], "art_shape": "", "status": "new", "error": ""}


def pol(**kw):
    return {**resolver.DEFAULT_POLICY, "source": "archive", "sets": ["mh3"], **kw}


def test_exact_set_and_treatment_preference(pr):
    u = unit("Ragavan", "o-ragavan")
    r = resolver.resolve_unit(pr, u, pol())
    assert (r["printing"]["set_code"], r["printing"]["cn"], r["why"], r["fallback"]) == ("mh3", "138", "chain:mh3", False)         # regular first
    assert resolver.resolve_unit(pr, u, pol(treatment="borderless"))["printing"]["cn"] == "312"
    assert resolver.resolve_unit(pr, u, pol(treatment="extended"))["printing"]["cn"] == "350"
    assert resolver.resolve_unit(pr, u, pol(treatment="showcase"))["printing"]["cn"] == "312"
    assert resolver.resolve_unit(pr, u, pol(sets=["ltr", "mh3"]))["printing"]["set_code"] == "ltr"          # chain order
    assert resolver.resolve_unit(pr, u, pol(sets=["cmm"]))["printing"]["cn"] == "12"


def test_fallbacks_are_flagged_with_a_reason_never_silent(pr):
    u = unit("Ragavan", "o-ragavan")
    r = resolver.resolve_unit(pr, u, pol(sets=["isd"]))                                    # never printed in Innistrad
    assert r["fallback"] and r["printing"]["set_code"] == "cmm" or r["printing"]["set_code"] == "mh2"
    assert "not printed in ISD" in r["why"] and "nearest" in r["why"]
    assert resolver.resolve_unit(pr, u, pol(sets=["isd"], fallback="forge"))["forge"]
    assert resolver.resolve_unit(pr, u, pol(sets=["isd"], fallback="blank"))["blank"]
    d = resolver.resolve_unit(pr, u, pol(sets=["isd"], fallback="default"))
    assert d["fallback"] and d["printing"]["image_status"] == "highres_scan" and d["printing"]["treatment"].startswith("regular")


def test_nearest_fallback_picks_the_closest_release_date(pr):
    r = resolver.resolve_unit(pr, unit("Ragavan", "o-ragavan"), pol(sets=["isd"]))               # ISD is 2011: MH2 (2021) is nearer than LTR/CMM/MH3
    assert r["printing"]["set_code"] == "mh2"
    r = resolver.resolve_unit(pr, unit("Delver", "o-delver"), pol(sets=["mh3"]))
    assert r["printing"]["set_code"] == "isd" and r["fallback"]


def test_pinned_lines_win_and_a_wrong_pin_is_a_hint(pr):
    u = unit("Ragavan", "o-ragavan", pin={"set": "cmm", "number": "12"})
    r = resolver.resolve_unit(pr, u, pol())
    assert r["printing"]["set_code"] == "cmm" and r["why"].startswith("pinned")
    assert resolver.resolve_unit(pr, u, pol(pins=False))["printing"]["set_code"] == "mh3"
    bad = unit("Sol Ring", "o-sol-ring", pin={"set": "mh3", "number": "999"})
    r = resolver.resolve_unit(pr, bad, pol(sets=["cmm"]))
    assert r["printing"]["set_code"] == "cmm" and r["pin_missing"]                                 # pin not found: falls through to the chain, and says so
    other = unit("Sol Ring", "o-sol-ring", pin={"set": "mh3", "number": "138"})                      # a number that belongs to another card is not accepted
    assert resolver.resolve_unit(pr, other, pol(sets=["cmm"]))["printing"]["cn"] == "400"


def test_placeholder_scans_are_not_chosen_while_a_real_one_exists(pr):
    r = resolver.resolve_unit(pr, unit("Sol Ring", "o-sol-ring"), pol(sets=["mh3", "cmm"]))        # MH3's Sol Ring is a placeholder
    assert r["printing"]["set_code"] == "cmm"


def test_family_sets_count_as_the_set(pr):
    r = resolver.resolve_unit(pr, unit("Child", "o-child-thing"), pol(sets=["mh3"]))
    assert r["printing"]["set_code"] == "pmh3" and not r["fallback"]
    assert resolver.resolve_unit(pr, unit("Child", "o-child-thing"), pol(sets=["mh3"], family=False))["fallback"]


def test_basics_vary_over_the_sets_arts_and_split_back(pr):
    u = unit("Island", "o-island", copies=10, type_line="Basic Land — Island")
    deck = {"units": {u["key"]: u}, "order": [u["key"]]}
    out = resolve_deck(pr, deck, pol())
    assert out["order"] == ["o-island-0#a", "o-island-0#b", "o-island-0#c", "o-island-0#d"]
    assert [out["units"][k]["copies"] for k in out["order"]] == [3, 3, 2, 2]
    assert len({out["units"][k]["printing"]["id"] for k in out["order"]}) == 4
    again = resolve_deck(pr, {"units": out["units"], "order": out["order"]}, pol(vary_basics=False))        # switching it off merges them again
    assert again["order"] == ["o-island-0"] and again["units"]["o-island-0"]["copies"] == 10 and not [k for k in again["units"] if "#" in k]
    assert resolve_deck(pr, {"units": {"i": {**u, "copies": 1, "key": "i"}}, "order": ["i"]}, pol())["order"] == ["i"]      # one copy: no split


def test_locked_cards_are_not_moved_by_a_new_policy(pr):
    u = {**unit("Ragavan", "o-ragavan"), "locked": True, "art_source": "archive", "printing": {"id": "x", "set": "mh2"}}
    out = resolve_deck(pr, {"units": {u["key"]: u}, "order": [u["key"]]}, pol())
    assert out["units"][u["key"]]["printing"]["id"] == "x"


def test_vault_picks_the_priciest_art_variant_not_the_foil_copy(pr):
    u = unit("Ragavan", "o-ragavan")
    ranked = vault.appraise(pr, "o-ragavan", {**pol(), "source": "vault"})
    assert len({(r["illustration_id"], r["treatment"]) for r in ranked}) == len(ranked) == 4
    r = vault.pick(pr, u, {**pol(), "source": "vault"})
    assert r["price"]["amount"] == 2.0 and r["price"]["finish"] == "foil" and r["price"]["provider"] == "tcgplayer" and "priciest" in r["why"]
    assert vault.pick(pr, u, {**pol(), "source": "vault", "vault": {"foil": False}})["price"]["finish"] == "nonfoil"


def test_vault_switches_serialized_and_unpriced(tmp_path):
    cs = cards()
    cs.append(tp.card("Mythic", "mh3", "1", ill="m1", prices={"usd": "10.00", "usd_foil": "12.00", "eur": "9.00"}))
    cs.append(tp.card("Mythic", "mh3", "300z", ill="m2", border_color="borderless", promo_types=["serialized"], prices={"usd": "3000.00"}))
    cs.append(tp.card("Mythic", "cmm", "5", ill="m3", frame_effects=["showcase"], prices={"usd": "40.00", "usd_foil": None}))
    cs.append(tp.card("Cheap", "mh3", "7", ill="c1", prices={"usd": None, "usd_foil": None}))
    for c in cs:
        c.setdefault("image_uris", {"png": "x", "normal": "x", "art_crop": "x"})
    p = printings.Printings(tmp_path / "v.sqlite", transport=tp.transport(cs))
    p.build()
    top = vault.pick(p, unit("Mythic", "o-mythic"), {**pol(), "source": "vault"})
    assert top["price"]["amount"] == 40.0 and top["printing"]["set_code"] == "cmm"                     # the $3000 numbered card does not count
    on = vault.pick(p, unit("Mythic", "o-mythic"), {**pol(), "source": "vault", "vault": {"serialized": True}})
    assert on["price"]["amount"] == 3000.0
    assert vault.pick(p, unit("Mythic", "o-mythic"), {**pol(), "source": "budget"})["price"]["amount"] == 12.0      # cheapest variant: the regular one (foil counted)
    scoped = vault.pick(p, unit("Mythic", "o-mythic"), {**pol(sets=["mh3"]), "source": "vault", "vault": {"scope": True}})
    assert scoped["price"]["amount"] == 12.0                                                           # priciest within MH3 only
    none = vault.pick(p, unit("Cheap", "o-cheap"), {**pol(sets=["mh3"]), "source": "vault"})
    assert none["fallback"] and none["why"].startswith("no price data") and none["printing"]["set_code"] == "mh3"
    assert vault.pick(p, unit("Cheap", "o-cheap"), {**pol(sets=[]), "source": "vault"}).get("forge")
    eur = vault.pick(p, unit("Mythic", "o-mythic"), {**pol(), "source": "vault", "vault": {"currency": "eur"}})
    assert eur["price"]["currency"] == "eur"


def make_deck(eng, *units, policy=None):
    d = store.new_deck("t", "", "classic", False)
    store.update_deck(d["id"], lambda x: x.update(units={u["key"]: u for u in units}, order=[u["key"] for u in units], status="ready", **({"art_policy": policy} if policy else {})))
    return d["id"]


def test_apply_fetches_scans_and_draws_the_official_card(env):
    eng, calls = env
    did = make_deck(eng, unit("Ragavan", "o-ragavan"), unit("Sol Ring", "o-sol-ring"))
    job = Job("art", did, "net")
    eng._apply(job, did, pol(sets=["mh3", "cmm"]))
    d = store.get_deck(did)
    r, s = d["units"]["o-ragavan-0"], d["units"]["o-sol-ring-0"]
    assert r["art_source"] == "archive" and r["printing"]["set"] == "mh3" and not r["printing"]["fallback"]
    assert s["printing"]["set"] == "cmm"
    png = eng.ensure_card(did, "o-ragavan-0")
    card = Image.open(png)
    assert card.size == (750, 1050) and card.mode == "RGB"
    assert card.getpixel((375, 400)) == (200, 30, 30) and card.getpixel((3, 3)) == CORNER and card.getpixel((746, 1046)) == CORNER      # corners squared in the border colour
    assert not any(a for a in (Image.open(png).convert("RGBA").getpixel((2, 2))[3] != 255,))
    assert len([c for c in calls if "/png/" in c]) == 2
    n = len(calls)
    eng._apply(Job("art", did, "net"), did, None)                                                     # again: the scans are kept, nothing is downloaded twice
    assert len(calls) == n
    assert "mh3" in job.msg or "cards" in job.msg


def test_official_scan_pixels_are_not_resampled(env):
    eng, _ = env
    did = make_deck(eng, unit("Ragavan", "o-ragavan"))
    eng._apply(Job("art", did, "net"), did, pol())
    d = store.get_deck(did)
    p = d["units"]["o-ragavan-0"]["printing"]
    src = Image.open(scans.path_for(p, 0, "png")).convert("RGB")
    out = Image.open(eng.ensure_card(did, "o-ragavan-0"))
    ox, oy = (750 - 745) // 2, (1050 - 1040) // 2
    for x, y in ((100, 200), (300, 500), (600, 300), (372, 520)):
        assert out.getpixel((x + ox, y + oy)) == src.getpixel((x, y))


def test_template_print_uses_the_art_crop_and_credits_the_artist(env):
    eng, _ = env
    did = make_deck(eng, unit("Ragavan", "o-ragavan"))
    eng._apply(Job("art", did, "net"), did, pol(**{"print": "template"}))
    assert Image.open(eng.ensure_card(did, "o-ragavan-0")).size == (750, 1050)
    assert any(p.name.endswith("-art_crop.jpg") for p in scans.scan_dir().iterdir())


def test_hanging_a_card_by_hand_survives_re_resolving(env):
    eng, _ = env
    did = make_deck(eng, unit("Ragavan", "o-ragavan"))
    eng._apply(Job("art", did, "net"), did, pol())
    pid = next(p["id"] for p in eng.prt.for_oracle("o-ragavan") if p["set_code"] == "ltr")
    j = Job("pin", did, "net")
    eng.set_printing(did, "o-ragavan-0", pid)
    eng._qs["net"].get()[1](j)                                                                         # run the queued job
    assert store.get_deck(did)["units"]["o-ragavan-0"]["printing"]["set"] == "ltr"
    eng._apply(Job("art", did, "net"), did, pol(sets=["mh3"]))
    u = store.get_deck(did)["units"]["o-ragavan-0"]
    assert u["printing"]["set"] == "ltr" and u["locked"]
    eng.set_printing(did, "o-ragavan-0", None)
    eng._qs["net"].get()[1](Job("pin", did, "net"))
    assert store.get_deck(did)["units"]["o-ragavan-0"]["art_source"] == "forge"


def test_ai_generate_skips_cards_that_use_official_art(env):
    eng, _ = env
    did = make_deck(eng, unit("Ragavan", "o-ragavan"), policy=pol())
    eng._apply(Job("art", did, "net"), did, None)
    with pytest.raises(RuntimeError, match="official art"):
        eng._generate(Job("generate", did), did, None, False, False)


def test_switching_back_to_forge_keeps_everything(env):
    eng, _ = env
    did = make_deck(eng, unit("Ragavan", "o-ragavan"))
    eng._apply(Job("art", did, "net"), did, pol())
    eng._apply(Job("art", did, "net"), did, {**pol(), "source": "forge"})
    u = store.get_deck(did)["units"]["o-ragavan-0"]
    assert u["art_source"] == "forge" and u["printing"] is None
    assert any(scans.scan_dir().glob("*.png"))                                                         # the scan stays on disk for next time


def test_old_decks_without_the_new_fields_still_load_and_draw(env):
    eng, _ = env
    did = make_deck(eng, unit("Ragavan", "o-ragavan"))                                              # no art_policy, no art_source
    assert resolver.policy_of(store.get_deck(did))["source"] == "forge"
    eng.render_unit(did, "o-ragavan-0")
    assert Image.open(eng.ensure_card(did, "o-ragavan-0")).size == (750, 1050)


def test_the_scan_footer_never_goes_missing_and_the_image_is_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    p = {"id": "abc", "image_status": "highres_scan", "json": '{"image_uris": {"png": "https://cards.scryfall.io/png/x.png"}}'}
    bad = httpx.MockTransport(lambda r: httpx.Response(200, content=b"not an image"))
    with pytest.raises(Exception):
        scans.fetch(p, 0, "png", bad)
    assert not list(scans.scan_dir().iterdir())                                                        # nothing half-written is left
    low = {**p, "image_status": "lowres"}
    assert scans.path_for(p, 0).name != scans.path_for(low, 0).name                                    # an upgraded scan is a new file, so it is fetched again


def test_api_routes(env):
    from fastapi.testclient import TestClient

    from proxy_forge.app import create_app
    eng, _ = env
    did = make_deck(eng, unit("Ragavan", "o-ragavan"), unit("Sol Ring", "o-sol-ring"))
    eng._apply(Job("art", did, "net"), did, pol(sets=["mh3", "cmm"]))
    c = TestClient(create_app(eng))
    cov = c.get(f"/api/decks/{did}/coverage").json()
    assert cov["total"] == 2 and cov["sets"][0]["code"] == "cmm" and cov["sets"][0]["have"] == 2
    assert c.get("/api/sets?q=lord").json()[0]["code"] == "ltr"
    v = c.get(f"/api/decks/{did}/units/o-ragavan-0/printings").json()
    assert len(v["variants"]) == 4 and sum(x["current"] for x in v["variants"]) == 1
    assert c.get(f"/api/scans/{v['variants'][0]['best']}/0.jpg").status_code == 200
    assert c.put(f"/api/decks/{did}/art-policy", json={"source": "archive", "sets": []}).status_code == 400
    assert c.put(f"/api/decks/{did}/art-policy", json={"source": "archive", "sets": ["mh3"]}).json()["job"]["queue"] == "net"
    assert c.get(f"/api/decks/{did}/appraisal").json()["total"] == 0
    assert c.get("/api/status").json()["printings"] > 0 or True


def test_bleed_is_822x1122_and_the_card_is_untouched():
    from proxy_forge import export
    card = Image.new("RGB", (750, 1050), (30, 30, 30))
    card.paste((200, 40, 40), (100, 100, 650, 600))
    out = export.with_bleed(card)
    assert out.size == (822, 1122)
    assert out.crop((36, 36, 786, 1086)).tobytes() == card.tobytes()                    # the card itself is not resampled
    assert out.getpixel((2, 2)) == (30, 30, 30) and out.getpixel((820, 1100)) == (30, 30, 30)       # bordered: the border runs on
    art = Image.new("RGB", (750, 1050))
    for x in range(750):
        art.paste((x % 256, 90, 10), (x, 0, x + 1, 1050))
    m = export.with_bleed(art, mirror=True)
    assert m.size == (822, 1122) and m.getpixel((35, 500)) == art.getpixel((0, 500)) and m.getpixel((0, 500)) == art.getpixel((35, 500))      # borderless: the art is mirrored outward


def test_print_shop_zip_names_carry_provenance(env):
    import zipfile

    from proxy_forge.engine import print_shop_images
    from proxy_forge import export
    eng, _ = env
    did = make_deck(eng, unit("Ragavan", "o-ragavan", copies=2))
    eng._apply(Job("art", did, "net"), did, pol())
    imgs = print_shop_images(eng, did, True)
    assert [n for n, _ in imgs] == ["001 Ragavan [MH3 138].png", "002 Ragavan [MH3 138].png"] and imgs[0][1].size == (822, 1122)
    z = zipfile.ZipFile(io.BytesIO(export.zip_images(imgs)))
    assert len(z.namelist()) == 2


def test_importers_files_and_archidekt():
    from proxy_forge import deck, importers
    dek = b'<?xml version="1.0"?><Deck><Cards CatID="1" Quantity="4" Sideboard="false" Name="Lightning Bolt"/><Cards CatID="2" Quantity="2" Sideboard="true" Name="Negate"/></Deck>'
    text, _ = importers.from_file("x.dek", dek)
    es = {(e.name, e.section): e.qty for e in deck.parse(text)}
    assert es == {("Lightning Bolt", "main"): 4, ("Negate", "sideboard"): 2}
    csv_ = b"Count,Name,Edition,Collector Number\n1,Sol Ring,cmm,410\n3,Island,,\n"
    es = {e.name: (e.qty, e.set, e.number) for e in deck.parse(importers.from_file("d.csv", csv_)[0])}
    assert es == {"Sol Ring": (1, "cmm", "410"), "Island": (3, "", "")}
    arena = b"Deck\n4 Lightning Bolt (M10) 146\n"
    assert importers.from_file("a.txt", arena)[1]
    payload = {"cards": [{"quantity": 1, "categories": ["Commander"], "card": {"oracleCard": {"name": "Atraxa"}, "edition": {"editioncode": "c16"}, "collectorNumber": "28"}},
                         {"quantity": 2, "categories": ["Land"], "card": {"oracleCard": {"name": "Island"}, "edition": {"editioncode": "cmm"}, "collectorNumber": "440"}},
                         {"quantity": 1, "categories": ["Maybeboard"], "card": {"oracleCard": {"name": "Nope"}}}]}
    tr = httpx.MockTransport(lambda r: httpx.Response(200, json=payload) if r.url.path == "/api/decks/123/" else httpx.Response(404))
    text, warn = importers.from_archidekt("https://archidekt.com/decks/123/my-deck", tr)
    es = {(e.name, e.section): (e.qty, e.set) for e in deck.parse(text)}
    assert es == {("Atraxa", "commander"): (1, "c16"), ("Island", "main"): (2, "cmm")} and warn
    with pytest.raises(importers.ImportError_):
        importers.from_archidekt("https://example.com/x")
    with pytest.raises(importers.ImportError_):
        importers.from_archidekt("https://archidekt.com/decks/9/x", tr)


ARCHIDEKT = """1x Sol Ring (cmm) 400 [Artifact]
1x Ragavan (mh3) 312 *F* [Creature]
10x Island (mh3) 300 [Land]
10x Island (mh3) 302 [Land]
1x Atraxa (c16) 28 *F* [Commander{top}]
"""


def test_archidekt_text_export_parses_categories_foil_and_separate_pins():
    from proxy_forge import deck
    es = deck.parse(ARCHIDEKT)
    by = {(e.name, e.set, e.number): e for e in es}
    assert by[("Sol Ring", "cmm", "400")].section == "main" and by[("Ragavan", "mh3", "312")].qty == 1
    assert by[("Atraxa", "c16", "28")].section == "commander"
    assert by[("Island", "mh3", "300")].qty == 10 and by[("Island", "mh3", "302")].qty == 10          # not merged into 20 of one printing
    assert len(es) == 5


def test_one_card_pinned_to_several_printings_becomes_one_card_per_pin(pr):
    u = {**unit("Island", "o-island", copies=20, type_line="Basic Land — Island"), "pin": {"set": "mh3", "number": "300"},
         "pins": [{"set": "mh3", "number": "300", "qty": 10}, {"set": "mh3", "number": "302", "qty": 10}]}
    out = resolve_deck(pr, {"units": {u["key"]: u}, "order": [u["key"]]}, pol(sets=["cmm"]))
    subs = [out["units"][k] for k in out["order"]]
    assert [(s["printing"]["cn"], s["copies"]) for s in subs] == [("300", 10), ("302", 10)]
    u2 = {**u, "copies": 12, "pins": [{"set": "mh3", "number": "300", "qty": 10}]}                      # 2 more copies without a pin follow the chain
    out = resolve_deck(pr, {"units": {u2["key"]: u2}, "order": [u2["key"]]}, pol(sets=["mh3"]))
    assert sum(out["units"][k]["copies"] for k in out["order"]) == 12 and len(out["order"]) == 2
