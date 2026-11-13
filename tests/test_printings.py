"""The printings index (M1): treatments, the build from a bulk file through a mock transport, and the local queries. No network, no GPU."""
import gzip
import json
import sqlite3

import httpx

from proxy_forge import printings, treatments

_n = [0]


def card(name, set_, cn, oracle="o-" , released="2024-01-01", **kw):
    _n[0] += 1
    c = {"object": "card", "id": f"id-{_n[0]}", "oracle_id": kw.pop("oid", oracle + name.lower().replace(" ", "-")), "name": name, "set": set_, "collector_number": cn,
         "released_at": released, "lang": "en", "layout": "normal", "illustration_id": kw.pop("ill", f"ill-{name}"), "artist": "A. Painter", "border_color": "black", "frame": "2015",
         "frame_effects": [], "promo_types": [], "finishes": ["nonfoil", "foil"], "full_art": False, "textless": False, "digital": False, "oversized": False,
         "games": ["paper"], "image_status": "highres_scan", "prices": {"usd": "1.00", "usd_foil": "2.00", "usd_etched": None, "eur": "0.80", "eur_foil": None}}
    c.update(kw)
    return c


def fixture():
    r = "Ragavan"
    cards = [
        card(r, "mh3", "138", released="2024-06-14", ill="ill-r1"),
        card(r, "mh3", "312", released="2024-06-14", ill="ill-r2", border_color="borderless", frame_effects=["showcase"]),
        card(r, "mh3", "350", released="2024-06-14", ill="ill-r1", frame_effects=["extendedart"]),
        card(r, "mh2", "138", released="2021-06-18", ill="ill-r1", image_status="lowres"),
        card(r, "ltr", "1", released="2023-06-23", ill="ill-r3"),
        card(r, "cmm", "12", released="2023-08-04", ill="ill-r1"),
        card(r, "mh3", "99", released="2024-06-14", digital=True, games=["arena"]),                     # digital: never a paper candidate
        card("Sol Ring", "cmm", "400", released="2023-08-04"),
        card("Sol Ring", "mh3", "300", released="2024-06-14", image_status="placeholder"),
        card("Island", "mh3", "300", released="2024-06-14", ill="isl1", oid="o-island"),
        card("Island", "mh3", "301", released="2024-06-14", ill="isl2", oid="o-island"),
        card("Island", "mh3", "302", released="2024-06-14", ill="isl3", oid="o-island"),
        card("Island", "mh3", "303", released="2024-06-14", ill="isl4", oid="o-island"),
        card("Foil Only Thing", "mh3", "20", finishes=["foil"], prices={"usd": None, "usd_foil": "5.50"}),
        card("Serial Card", "mh3", "400z", promo_types=["serialized"], prices={"usd": "3000.00"}),
        card("Delver of Secrets // Insectile Aberration", "isd", "51", layout="transform", oid=None, ill=None, released="2011-09-30",
             card_faces=[{"name": "Delver of Secrets", "oracle_id": "o-delver", "illustration_id": "ill-d0"}, {"name": "Insectile Aberration", "oracle_id": "o-delver", "illustration_id": "ill-d1"}]),
        card("Treasure", "tmh3", "5", layout="token"),
        card("Child Promo Thing", "pmh3", "9", oid="o-child-thing"),
    ]
    cards[15].pop("oracle_id")
    return cards


SETS = [{"code": "mh3", "name": "Modern Horizons 3", "set_type": "draft_innovation", "released_at": "2024-06-14", "card_count": 400, "icon_svg_uri": "https://svgs/mh3.svg"},
        {"code": "pmh3", "name": "MH3 Promos", "set_type": "promo", "released_at": "2024-06-14", "parent_set_code": "mh3", "card_count": 20},
        {"code": "mh2", "name": "Modern Horizons 2", "set_type": "draft_innovation", "released_at": "2021-06-18"},
        {"code": "ltr", "name": "The Lord of the Rings", "set_type": "expansion", "released_at": "2023-06-23"},
        {"code": "cmm", "name": "Commander Masters", "set_type": "masters", "released_at": "2023-08-04"},
        {"code": "isd", "name": "Innistrad", "set_type": "expansion", "released_at": "2011-09-30"},
        {"code": "ymh3", "name": "Arena MH3", "set_type": "expansion", "released_at": "2024-06-14", "digital": True}]


def transport(cards, calls=None):
    blob = gzip.compress("\n".join(json.dumps(c) for c in cards).encode())

    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(req.url))
        if req.url.path == "/bulk-data":
            return httpx.Response(200, json={"data": [{"type": "oracle_cards", "jsonl_download_uri": "https://data.scryfall.io/oracle.jsonl.gz"},
                                                      {"type": "default_cards", "jsonl_download_uri": "https://data.scryfall.io/default.jsonl.gz", "compressed_size": len(blob)}]})
        if req.url.host == "data.scryfall.io":
            assert "default" in req.url.path
            return httpx.Response(200, content=blob)
        if req.url.path == "/sets":
            return httpx.Response(200, json={"data": SETS})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def built(tmp_path):
    p = printings.Printings(tmp_path / "printings.sqlite", transport=transport(fixture()))
    p.build()
    return p


def test_treatment_keys():
    assert treatments.treatment({"frame": "2015"}) == "regular-2015"
    assert treatments.treatment({"frame": "1993", "border_color": "white"}) == "white"
    assert treatments.treatment({"border_color": "borderless", "frame_effects": ["showcase"]}) == "borderless-showcase"
    assert treatments.treatment({"frame_effects": ["extendedart"]}) == "extended"
    assert treatments.treatment({"frame_effects": ["etched", "inverted"]}) == "etched-inverted"
    assert treatments.treatment({"frame": "2015", "promo_types": ["galaxyfoil"]}) == "regular-2015"
    assert treatments.treatment({"frame": "2015", "promo_types": ["galaxyfoil"]}, look_promos=True) == "galaxyfoil"
    assert treatments.treatment({"frame_effects": ["legendary"], "frame": "2015"}) == "regular-2015"          # does not change the look
    assert treatments.treatment({"frame_effects": ["somethingnew"]}) == "somethingnew"
    assert treatments.label({"border_color": "borderless", "frame_effects": ["showcase"]}) == "Borderless · Showcase"
    assert treatments.label({"frame": "2003"}) == "Regular · 2003"


def test_build_skips_tokens_swaps_atomically_and_keeps_sets(tmp_path):
    p = built(tmp_path)
    assert p.count() == len(fixture()) - 1                                  # the token is not indexed
    assert not list(tmp_path.glob("*.part")) and not list(tmp_path.glob("*.new"))
    assert p.age() < 5 and not p.stale()
    assert {s["code"] for s in p.sets()} == {"mh3", "pmh3", "mh2", "ltr", "cmm", "isd"}      # digital sets are not offered
    assert p.sets("lord")[0]["code"] == "ltr" and p.sets(set_type="masters")[0]["code"] == "cmm"


def test_a_failed_build_leaves_the_old_index_in_use(tmp_path):
    p = built(tmp_path)
    before = p.count()

    def boom(req):
        return httpx.Response(500)
    p.transport = httpx.MockTransport(boom)
    try:
        p.build()
    except Exception:
        pass
    assert p.count() == before


def test_names_and_faces(tmp_path):
    p = built(tmp_path)
    ids = p.oracle_ids(["Ragavan", "  sol RING ", "Insectile Aberration", "Delver of Secrets", "Nope"])
    assert ids["Ragavan"] == "o-ragavan" and ids["  sol RING "] == "o-sol-ring"
    assert ids["Insectile Aberration"] == "o-delver" == ids["Delver of Secrets"]          # either face finds the card; oracle id taken from the face
    assert ids["Nope"] is None


def test_for_oracle_is_paper_only_newest_first(tmp_path):
    p = built(tmp_path)
    ps = p.for_oracle("o-ragavan")
    assert [(x["set_code"], x["cn"]) for x in ps] == [("mh3", "138"), ("mh3", "312"), ("mh3", "350"), ("cmm", "12"), ("ltr", "1"), ("mh2", "138")]
    assert len(p.for_oracle("o-ragavan", paper_only=False)) == 7


def test_in_sets_exact_set_chain_order_and_family(tmp_path):
    p = built(tmp_path)
    got = [(x["set_code"], x["cn"]) for x in p.in_sets("o-ragavan", ["mh3", "ltr"])]
    assert got == [("mh3", "138"), ("mh3", "312"), ("mh3", "350"), ("ltr", "1")]       # chain order, collector-number order inside a set
    assert [x["set_code"] for x in p.in_sets("o-ragavan", ["ltr", "mh3"])][0] == "ltr"
    assert p.in_sets("o-sol-ring", ["isd"]) == []                                     # never "the same name from another set"
    assert [x["set_code"] for x in p.in_sets("o-child-thing", ["mh3"], family=True)] == ["pmh3"]
    assert p.in_sets("o-child-thing", ["mh3"], family=False) == []
    assert p.family(["mh3"]) == ["mh3", "pmh3"]


def test_by_set_cn(tmp_path):
    p = built(tmp_path)
    r = p.by_set_cn("MH3", "312")
    assert r["treatment"] == "borderless-showcase" and r["oracle_id"] == "o-ragavan"
    assert p.by_set_cn("mh3", "9999") is None
    assert p.by_set_cn("mh3", "400z")["cn_num"] == 400


def test_coverage_counts_cards_not_printings_sorted(tmp_path):
    p = built(tmp_path)
    oids = ["o-ragavan", "o-sol-ring", "o-island", "o-delver"]
    cov = p.coverage(oids)
    assert cov["mh3"] == 3 and cov["cmm"] == 2 and cov["ltr"] == 1 and cov["isd"] == 1       # Ragavan has 3 printings in MH3 but counts once
    assert list(cov)[0] == "mh3" and list(cov.values()) == sorted(cov.values(), reverse=True)
    assert "ymh3" not in cov
    assert p.coverage([]) == {}


def test_variants_group_by_illustration_and_treatment(tmp_path):
    p = built(tmp_path)
    vs = p.variants("o-ragavan")
    keys = {(v["illustration_id"], v["treatment"]) for v in vs}
    assert keys == {("ill-r1", "regular-2015"), ("ill-r1", "extended"), ("ill-r2", "borderless-showcase"), ("ill-r3", "regular-2015")}
    plain = next(v for v in vs if v["illustration_id"] == "ill-r1" and v["treatment"] == "regular-2015")
    assert {x["set_code"] for x in plain["printings"]} == {"mh3", "cmm", "mh2"}             # same art, same frame, three sets: one variant
    assert plain["best"]["image_status"] == "highres_scan" and plain["best"]["set_code"] in ("mh3", "cmm")


def test_prices_and_flags_are_stored(tmp_path):
    p = built(tmp_path)
    foil = p.for_oracle("o-foil-only-thing")[0]
    assert foil["usd"] is None and foil["usd_foil"] == 5.5 and json.loads(foil["finishes"]) == ["foil"]
    assert "serialized" in json.loads(p.for_oracle("o-serial-card")[0]["promo_types"])
    assert json.loads(p.for_oracle("o-sol-ring")[0]["json"])["name"] == "Sol Ring"


def test_reads_the_legacy_single_array_and_plain_files(tmp_path):
    f = tmp_path / "old.json"
    f.write_text(json.dumps(fixture()[:3]))
    p = printings.Printings(tmp_path / "x.sqlite", transport=transport([]))
    assert p.build(source=f) == 3
    g = tmp_path / "plain.jsonl"
    g.write_text("\n".join(json.dumps(c) for c in fixture()[:4]) + "\n")
    assert p.build(source=g) == 4


def test_a_hundred_cards_resolve_in_well_under_a_second(tmp_path):
    import time
    cards = [card(f"Card {i}", "mh3", str(i), released="2024-06-14") for i in range(100)] + [card(f"Card {i}", "ltr", str(i), released="2023-06-23") for i in range(60)]
    p = printings.Printings(tmp_path / "p.sqlite", transport=transport(cards))
    p.build()
    names = [f"Card {i}" for i in range(100)]
    t = time.time()
    ids = p.oracle_ids(names)
    cov = p.coverage(list(ids.values()))
    chosen = [p.in_sets(o, ["mh3", "ltr"])[0] for o in ids.values()]
    assert time.time() - t < 1 and cov["mh3"] == 100 and cov["ltr"] == 60 and len(chosen) == 100


def test_the_file_is_a_plain_sqlite_with_the_documented_tables(tmp_path):
    p = built(tmp_path)
    db = sqlite3.connect(p.path)
    assert {r[0] for r in db.execute("select name from sqlite_master where type='table'")} >= {"printings", "names", "sets", "meta"}
