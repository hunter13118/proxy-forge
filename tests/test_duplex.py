"""Two-sided printing: a back must sit exactly behind its front. The tests flip the printed back page the way the paper is flipped and compare it, pixel for pixel, with the front. No printer needed."""
import io

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageStat

from proxy_forge import backs, export


def make(tmp_path, n, side):
    """An asymmetric picture (so a mirrored or turned one is caught): a unique colour per card, a dot in the top-left corner and a bar down the left edge."""
    im = Image.new("RGB", (750, 1050), (20 + 25 * n, 200 - 15 * n, 90 if side == "f" else 220))
    d = ImageDraw.Draw(im)
    d.ellipse((30, 30, 130, 130), fill="red")
    d.rectangle((0, 200, 40, 900), fill="black")
    p = tmp_path / f"{side}{n}.png"
    im.save(p)
    return p


def pairs(tmp_path, k):
    return [(make(tmp_path, n, "f"), make(tmp_path, n, "b")) for n in range(k)]


def mean_diff(a, b):
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


@pytest.mark.parametrize("flip", ["long", "short"])
@pytest.mark.parametrize("turn", ["never", "always"])
@pytest.mark.parametrize("paper", ["a4", "letter"])
def test_every_back_lies_exactly_behind_its_front(tmp_path, flip, turn, paper):
    ps = pairs(tmp_path, 9)
    fronts, backs_ = export.duplex_pages(ps, paper, turn=turn, flip=flip, marks=False)
    lay = export.best_layout(paper, turn=turn)
    physical = ImageOps.mirror(backs_[0]) if flip == "long" else ImageOps.flip(backs_[0])          # the sheet turned over: what shows through from the front
    angle = 90 if lay.turned else 0
    cw, ch = (lay.card[1], lay.card[0]) if lay.turned else lay.card
    for n in range(lay.per_page):                                                                  # 9 upright, 8 turned
        x, y = lay.cell(n)
        w, h = lay.card
        seen = physical.crop((x, y, x + w, y + h))
        back = Image.open(ps[n][1]).convert("RGB").resize((cw, ch), Image.LANCZOS)
        expect = ImageOps.mirror(back)                                                         # through the paper the back reads mirrored (card upright) ...
        expect = expect.rotate(angle, expand=True) if angle else expect                         # ... and turned the same way as its front
        assert seen.size == expect.size
        diff = mean_diff(seen, expect)
        assert diff < 3, f"slot {n}: the back is not behind its front (mean diff {diff})"
        front = fronts[0].crop((x, y, x + w, y + h))
        assert front.getpixel((w // 2, h // 2)) != seen.getpixel((w // 2, h // 2))               # they are different pictures, so the comparison above means something


def test_the_top_edges_meet_for_the_flip_that_was_asked_for(tmp_path):
    """The red dot marks a card's top-left. Upright cards: the front's dot is at the top-left of the slot; the back's dot is, through the paper, at the top-right."""
    ps = pairs(tmp_path, 1)
    lay = export.best_layout("a4", turn="never")
    x, y = lay.cell(0)
    f, b = export.duplex_pages(ps, "a4", turn="never", flip="long", marks=False)
    assert f[0].getpixel((x + 80, y + 80)) == (255, 0, 0)
    through = ImageOps.mirror(b[0])
    assert through.getpixel((x + lay.card[0] - 80, y + 80)) == (255, 0, 0) and through.getpixel((x + 80, y + 80)) != (255, 0, 0)
    f, b = export.duplex_pages(ps, "a4", turn="never", flip="short", marks=False)
    through = ImageOps.flip(b[0])
    assert through.getpixel((x + lay.card[0] - 80, y + 80)) == (255, 0, 0)                        # the same view through the paper, whichever way the sheet was turned


def test_back_slots_mirror_across_the_flip_axis():
    lay = export.best_layout("a4", turn="never")
    pw, ph = lay.page
    for n in range(lay.per_page):
        x, y = lay.cell(n)
        w, h = lay.card
        assert export.back_cell(lay, n, "long") == (pw - x - w, y) and export.back_cell(lay, n, "short") == (x, ph - y - h)
    bx, by = export.back_cell(lay, 0, "long")
    assert export.back_cell(lay, 0, "long", 12, -5) == (bx + 12, by - 5)                          # the owner's alignment shift


def test_alignment_shift_moves_only_the_backs(tmp_path):
    ps = pairs(tmp_path, 1)
    f0, b0 = export.duplex_pages(ps, "a4", turn="never", flip="long", marks=False)
    f1, b1 = export.duplex_pages(ps, "a4", turn="never", flip="long", marks=False, dx_mm=1.0, dy_mm=2.0)
    assert f0[0].tobytes() == f1[0].tobytes() and b0[0].tobytes() != b1[0].tobytes()
    lay = export.best_layout("a4", turn="never")
    x, y = export.back_cell(lay, 0, "long")
    assert b1[0].getpixel((x + 80 + 12, y + 80 + 24)) == b0[0].getpixel((x + 80, y + 80))        # 1 mm = 12 px at 300 dpi


def test_page_order_for_auto_and_manual(tmp_path):
    ps = pairs(tmp_path, 20)                                                                       # three sheets of nine, the last with two cards
    f, b = export.duplex_pages(ps, "a4", turn="never", marks=False)
    assert len(f) == len(b) == 3
    assert export.duplex_order(f, b, "auto") == [f[0], b[0], f[1], b[1], f[2], b[2]]               # front, back, front, back ...
    assert export.duplex_order(f, b, "manual") == f + b                                           # all fronts, then all backs
    assert export.duplex_order(f, b, "manual", reverse_backs=True) == f + b[::-1]
    assert export.duplex_order(f, b, "manual", part="fronts") == f and export.duplex_order(f, b, "manual", part="backs") == b
    assert export.duplex_order(f, b, "none") == f
    assert export.pages_pdf(export.duplex_order(f, b, "auto"))[:4] == b"%PDF"


def test_a_missing_back_leaves_its_slot_blank_but_keeps_the_page(tmp_path):
    ps = [(make(tmp_path, 0, "f"), None), (make(tmp_path, 1, "f"), None)]
    f, b = export.duplex_pages(ps, "a4", marks=False)
    assert len(b) == 1 and b[0].convert("L").getextrema() == (255, 255)                           # a blank back page: sheets stay in step


def test_backs_on_the_outside_of_the_grid_bleed_5mm_past_the_cut(tmp_path):
    """A back with a green strip down its left edge: the cards on the grid's left column get that strip continued 5 mm (59 px) outside the cut; interior cards get nothing extra."""
    green = Image.new("RGB", (750, 1050), (0, 0, 255))
    ImageDraw.Draw(green).rectangle((0, 0, 39, 1049), fill=(0, 255, 0))
    bp_ = tmp_path / "green.png"
    green.save(bp_)
    ps = [(make(tmp_path, n, "f"), bp_) for n in range(9)]
    f, b = export.duplex_pages(ps, "a4", turn="never", flip="long", marks=False)
    lay = export.best_layout("a4", turn="never")
    for n in range(9):
        x, y = export.back_cell(lay, n, "long")
        outer = abs(x - lay.origin[0]) <= 2
        if outer:
            assert b[0].getpixel((x - 30, y + 500)) == (0, 255, 0)                                  # inside the bleed: the strip goes on
            assert b[0].getpixel((x - 70, y + 500)) == (255, 255, 255)                              # past 5 mm: plain paper again
    assert export.duplex_pages(ps, "a4", turn="never", marks=False, back_bleed_mm=0)[1][0].tobytes() != b[0].tobytes()


def test_with_a_gap_the_bleed_runs_into_the_white_space_and_stops_there(tmp_path):
    """Sides that face white space (the gap, or the outside of the block) take bleed; a bleed longer than the gap is clamped to it, so it never reaches the neighbour's card."""
    green = Image.new("RGB", (750, 1050), (0, 0, 255))
    ImageDraw.Draw(green).rectangle((0, 0, 39, 1049), fill=(0, 255, 0))
    bp_ = tmp_path / "green2.png"
    green.save(bp_)
    ps = [(make(tmp_path, n, "f"), bp_) for n in range(9)]
    gap_mm = 2.0
    f, b = export.duplex_pages(ps, "a4", turn="never", flip="long", marks=False, gap_mm=gap_mm)
    lay = export.best_layout("a4", turn="never", gap_mm=gap_mm)
    bleed = export._px(5.0)
    gap = export._px(gap_mm)
    assert lay.gap == gap
    interior = [n for n in range(9) if abs(export.back_cell(lay, n, "long")[0] - lay.origin[0]) > 2]
    for n in interior:
        x, y = export.back_cell(lay, n, "long")
        assert export._bleed_amounts(lay, (x, y), bleed)[0] == gap // 2                           # half the gap: the neighbours' bleeds meet, never overlap
        assert b[0].getpixel((x - gap // 4, y + 500)) == (0, 255, 0)                              # the bleed is in the white space
    x, y = export.back_cell(lay, 0, "long") if abs(export.back_cell(lay, 0, "long")[0] - lay.origin[0]) <= 2 else export.back_cell(lay, 2, "long")
    assert export._bleed_amounts(lay, (x, y), bleed)[0] == bleed                                  # on the outside, the full 5 mm


def test_layout_route_matches_the_pdf_layout_and_a_gap_can_change_it(env):
    from fastapi.testclient import TestClient

    from proxy_forge.app import create_app
    eng, _ = env
    c = TestClient(create_app(eng))
    for paper, gap in (("a4", 0), ("letter", 0), ("letter", 3), ("a4", 6)):
        lay = export.best_layout(paper, "mtg", 5.0, float(gap), "auto")
        r = c.get(f"/api/layout?paper={paper}&gap={gap}").json()
        assert (r["cols"], r["rows"], r["turned"], r["per_page"]) == (lay.cols, lay.rows, lay.turned, lay.per_page)
    assert c.get("/api/layout?paper=letter&gap=0").json()["per_page"] == 9
    assert c.get("/api/layout?paper=letter&gap=3").json()["per_page"] < 9                              # 3 rows no longer fit the printable height with a gap
    assert c.get("/api/layout?paper=a4&gap=0").json()["card_mm"] == [63.0, 88.0]
    room = c.get("/api/layout?paper=letter&gap=0").json()["room_mm"]
    assert abs(room[1] - room[3]) < 0.1 and room[1] < 5 and abs(room[0] - room[2]) < 0.1 and room[0] > 5       # Letter: 2.7 mm of printable bleed above and below, 8.4 mm at the sides
    assert c.get("/api/layout?paper=foolscap").status_code == 400 and c.get("/api/layout?gap=99").status_code == 400


def test_outside_bleed_is_capped_at_what_the_printer_can_reach(tmp_path):
    """US Letter, 3 x 3: the block leaves 7.7 mm above and below, the printer cannot reach the outer 5 mm, so only 2.7 mm of bleed would print there. A4 has room for all 5."""
    margin = export._px(5.0)
    bleed = export._px(5.0)
    lay = export.best_layout("letter", turn="never")
    l, t, r, b = export.block_room(lay, margin)
    assert t == lay.origin[1] - margin and abs(t - b) <= 1 and t < bleed and abs(l - r) <= 1 and min(l, r) >= bleed        # the block is centred to within a pixel
    x, y = export.back_cell(lay, 0, "long")                                                       # a back in the top row
    assert export._bleed_amounts(lay, (x, y), bleed, margin)[1] == t                                # top: capped; the sides keep the full bleed
    assert export._bleed_amounts(lay, (lay.origin[0], y), bleed, margin)[0] == bleed
    a4 = export.best_layout("a4", turn="never")
    assert min(export.block_room(a4, margin)) >= bleed
    blue = Image.new("RGB", (750, 1050), (0, 0, 255))
    bp_ = tmp_path / "blue.png"
    blue.save(bp_)
    f, back = export.duplex_pages([(make(tmp_path, 0, "f"), bp_)], "letter", turn="never", marks=False)
    assert back[0].getpixel((x + 300, y - t // 2)) == (0, 0, 255)                                 # inside the printable bleed
    assert back[0].getpixel((x + 300, y - t - 6)) == (255, 255, 255)                              # past the printer's limit: nothing


def test_guides_run_through_the_gaps_but_not_between_touching_cards(tmp_path):
    ps = pairs(tmp_path, 6)
    lay = export.best_layout("letter", turn="never", gap_mm=3.0)
    f, b = export.duplex_pages(ps, "letter", turn="never", gap_mm=3.0, marks=True)
    ink = (17, 17, 17)
    x = lay.origin[0] + (lay.card[0] + lay.gap) - 3                                                # just left of the second column, in the gap
    y = lay.origin[1] + lay.card[1] + lay.gap - 3                                                  # just above the second row, in the gap
    for pg in (f[0], b[0]):
        assert pg.getpixel((x, lay.origin[1] + 5)) == ink and pg.getpixel((lay.origin[0] + 5, y)) == ink
        assert pg.getpixel((lay.origin[0] + 5, lay.origin[1] + 5)) != ink                         # the card itself is untouched
    a4 = export.best_layout("a4", turn="never")                                                    # no gap: no guides on the pictures
    on = export.duplex_pages(ps, "a4", turn="never", marks=True)[0][0]
    off = export.duplex_pages(ps, "a4", turn="never", marks=False)[0][0]
    box = (a4.origin[0], a4.origin[1], a4.origin[0] + 3 * a4.card[0], a4.origin[1] + 3 * a4.card[1])
    assert on.crop(box).tobytes() == off.crop(box).tobytes()


def test_bad_flip_is_refused(tmp_path):
    with pytest.raises(ValueError):
        export.duplex_pages(pairs(tmp_path, 1), flip="diagonal")


@pytest.mark.parametrize("paper", ["a4", "letter"])
def test_test_sheet_has_a_front_and_a_matching_back(paper):
    pg = export.test_sheets(paper, flip="long")
    assert len(pg) == 2 and pg[0].size == pg[1].size == export.PAPER[paper] and pg[0].tobytes() != pg[1].tobytes()
    lay = export.best_layout(paper)
    x, y = lay.cell(0)
    cx, cy = x + lay.card[0] // 2, y + lay.card[1] // 2
    assert (255, 0, 0) in {c for _, c in pg[0].crop((cx - 40, cy - 3, cx + 40, cy + 3)).getcolors()}      # a red cross at the centre of the slot
    bx, by = export.back_cell(lay, 0, "long")
    assert (bx + lay.card[0] // 2, by + lay.card[1] // 2) == (lay.page[0] - cx, cy)                      # and its twin at the mirrored centre
    assert (255, 0, 0) in {c for _, c in pg[1].crop((lay.page[0] - cx - 40, cy - 3, lay.page[0] - cx + 40, cy + 3)).getcolors()}


def test_funny_backs_are_card_sized_and_cached(tmp_path, monkeypatch):
    from proxy_forge import config
    monkeypatch.setattr(config, "DATA", tmp_path)
    for d in backs.FUNNY:
        im = backs.funny(d["id"])
        assert im.size == (750, 1050) and im.mode == "RGB" and im.getcolors(maxcolors=50) is None            # not a flat colour
    assert len(list((tmp_path / "backs").glob("funny-*.png"))) == len(backs.FUNNY)


def test_official_back_is_fetched_once_and_squared(tmp_path, monkeypatch):
    import httpx

    from proxy_forge import config
    monkeypatch.setattr(config, "DATA", tmp_path)
    calls = []
    raw = io.BytesIO()
    im = Image.new("RGBA", (745, 1040), (40, 20, 10, 255))
    im.putpixel((0, 0), (0, 0, 0, 0))
    im.save(raw, "PNG")

    def h(req):
        calls.append(str(req.url))
        return httpx.Response(200, content=raw.getvalue())
    t = httpx.MockTransport(h)
    a = backs.official(t)
    backs.official(t)
    assert len(calls) == 1 and a.size == (750, 1050) and a.getpixel((1, 1)) == (40, 20, 10)
    assert "backs.scryfall.io" in calls[0]


def test_ai_back_is_framed_and_cover_fits_any_picture():
    out = backs.ai_frame(Image.new("RGB", (832, 1216), "#335577"))
    assert out.size == (750, 1050) and out.getpixel((10, 10)) == (11, 11, 11) and out.getpixel((375, 525)) == (51, 85, 119)
    assert backs.cover(Image.new("RGB", (4000, 300), "red")).size == (750, 1050)


# ------------------------------------------------------------------------------------------------------------------------------------------------------ the deck, the engine, the routes
from test_archive import env, make_deck, unit  # noqa: E402,F401
from proxy_forge import store  # noqa: E402
from proxy_forge.engine import Job  # noqa: E402


def dfc_units():
    a = {**unit("Delver of Secrets", "o-delver", key="o-delver-0"), "face": 0, "faces": 2}
    b = {**unit("Insectile Aberration", "o-delver", key="o-delver-1"), "face": 1, "faces": 2}
    return a, b


def test_a_double_faced_cards_other_side_is_its_back_and_is_not_printed_twice(env):
    eng, _ = env
    a, b = dfc_units()
    did = make_deck(eng, a, b, unit("Sol Ring", "o-sol-ring"))
    pairs_ = eng.print_pairs(did, True, False, duplex=True)
    assert len(pairs_) == 2                                                          # the DFC (one sheet slot) and Sol Ring
    assert pairs_[0][1] == eng.ensure_card(did, "o-delver-1") and pairs_[1][1] is None            # Delver's back is Insectile Aberration; Sol Ring has no back yet
    store.update_deck(did, lambda d: d.update(back={"mode": "funny", "funny": "duck", "dfc": False}))
    p2 = eng.print_pairs(did, True, False, duplex=True)
    assert len(p2) == 3 and all(b_ is not None and b_.name == "back.png" for _, b_ in p2)          # dfc off: three cards, all on the deck's back
    assert len(eng.print_pairs(did, True, False, duplex=False)) == 3 and all(b_ is None for _, b_ in eng.print_pairs(did, True, False, duplex=False))


def test_set_back_and_the_two_sided_pdf_route(env):
    from fastapi.testclient import TestClient

    from proxy_forge.app import create_app
    eng, _ = env
    did = make_deck(eng, unit("Sol Ring", "o-sol-ring", copies=10))
    c = TestClient(create_app(eng))
    assert c.get(f"/api/decks/{did}/export.pdf?duplex=auto").status_code == 400                    # no back chosen yet: it says so instead of printing blanks
    assert c.put(f"/api/decks/{did}/back", json={"mode": "ai"}).status_code == 400
    assert c.put(f"/api/decks/{did}/back", json={"mode": "custom"}).status_code == 400
    assert c.put(f"/api/decks/{did}/back", json={"mode": "funny", "funny": "nope"}).status_code == 400
    r = c.put(f"/api/decks/{did}/back", json={"mode": "funny", "funny": "swirl"})
    assert r.json()["job"]["queue"] == "net"
    eng._qs["net"].get()[1](Job("back", did, "net"))
    assert c.get(f"/api/decks/{did}/back.jpg").headers["content-type"] == "image/jpeg"
    pages = lambda r_: r_.content.count(b"/Type /Page\n") + r_.content.count(b"/Type /Page ") + r_.content.count(b"/Type/Page/")
    auto = c.get(f"/api/decks/{did}/export.pdf?duplex=auto&paper=a4")
    assert auto.status_code == 200 and auto.content[:4] == b"%PDF" and "auto" in auto.headers["content-disposition"]
    manual = c.get(f"/api/decks/{did}/export.pdf?duplex=manual&paper=a4&part=backs&flip=short&back_dx=0.5&back_dy=-0.5&reverse_backs=true")
    assert manual.status_code == 200 and "backs" in manual.headers["content-disposition"]
    assert c.get(f"/api/decks/{did}/export.pdf?duplex=sideways").status_code == 400
    assert c.get(f"/api/decks/{did}/export.pdf?duplex=auto&flip=diagonal").status_code == 400
    assert c.get(f"/api/decks/{did}/export.pdf?duplex=auto&back_dx=99").status_code == 400
    plain = c.get(f"/api/decks/{did}/export.pdf?paper=a4")
    assert plain.status_code == 200 and len(auto.content) > len(plain.content)                     # the two-sided file carries the backs too
    t = c.get("/api/duplex-test.pdf?paper=letter&flip=short")
    assert t.status_code == 200 and t.content[:4] == b"%PDF"
    assert c.get("/api/duplex-test.pdf?flip=up").status_code == 400
    assert {b["id"] for b in c.get("/api/backs").json()} >= {"mtg", "swirl", "tax"}
    assert c.get("/api/backs/duck.jpg").status_code == 200


def test_a_custom_back_is_cropped_to_the_card(env):
    from fastapi.testclient import TestClient

    from proxy_forge.app import create_app
    eng, _ = env
    did = make_deck(eng, unit("Sol Ring", "o-sol-ring"))
    c = TestClient(create_app(eng))
    buf = io.BytesIO()
    Image.new("RGB", (1600, 900), "#884400").save(buf, "PNG")
    r = c.post(f"/api/decks/{did}/back/custom", files={"file": ("mine.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200
    eng._qs["net"].get()[1](Job("back", did, "net"))
    assert Image.open(eng.back_path(did)).size == (750, 1050)
    assert c.post(f"/api/decks/{did}/back/custom", files={"file": ("x.png", b"not a picture", "image/png")}).status_code == 400
