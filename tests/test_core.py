import io

from PIL import Image

from proxy_forge import deck, export, prompts, render
from proxy_forge.scryfall import units


def test_deck_parse_formats():
    text = """Deck
4 Lightning Bolt
4x Counterspell (MH2) 267
1 Sol Ring *F*
// a comment
Sideboard
2 Negate
SB: 1 Duress
Commander
1 Atraxa, Praetors' Voice
Maybeboard
3 Brainstorm
"""
    es = {(e.name, e.section): e for e in deck.parse(text)}
    assert es[("Lightning Bolt", "main")].qty == 4
    assert es[("Counterspell", "main")].qty == 4 and es[("Counterspell", "main")].set == "mh2" and es[("Counterspell", "main")].number == "267"
    assert ("Sol Ring", "main") in es
    assert es[("Negate", "sideboard")].qty == 2 and es[("Duress", "sideboard")].qty == 1
    assert ("Atraxa, Praetors' Voice", "commander") in es
    assert es[("Brainstorm", "maybe")].qty == 3


def test_deck_merges_duplicates_and_plain_names():
    es = deck.parse("Island\n3 Island\n")
    assert len(es) == 1 and es[0].qty == 4


def test_units_split_and_dfc():
    split = {"oracle_id": "o1", "name": "Fire // Ice", "layout": "split", "colors": ["R", "U"], "card_faces": [
        {"name": "Fire", "mana_cost": "{1}{R}", "type_line": "Instant", "oracle_text": "Fire deals 2 damage."}, {"name": "Ice", "mana_cost": "{1}{U}", "type_line": "Instant", "oracle_text": "Tap target permanent."}]}
    u = units(split)
    assert len(u) == 1 and "Ice" in u[0]["oracle_text"] and u[0]["key"] == "o1-0"
    dfc = {"oracle_id": "o2", "name": "A // B", "layout": "transform", "card_faces": [
        {"name": "A", "mana_cost": "{2}", "type_line": "Creature", "oracle_text": "x", "power": "1", "toughness": "1", "colors": ["G"]},
        {"name": "B", "mana_cost": "", "type_line": "Creature", "oracle_text": "y", "power": "3", "toughness": "3", "colors": ["G"]}]}
    u = units(dfc)
    assert [x["key"] for x in u] == ["o2-0", "o2-1"] and u[1]["name"] == "B" and u[1]["faces"] == 2


def test_every_template_renders_at_print_size():
    for t in render.list_templates():
        for u in (render.sample_unit(), {"key": "l", "name": "Plains", "type_line": "Basic Land — Plains", "oracle_text": "({T}: Add {W}.)", "colors": []},
                  {"key": "s", "name": "Wrath of God", "type_line": "Sorcery", "mana_cost": "{2}{W}{W}", "oracle_text": "Destroy all creatures. They can't be regenerated.", "colors": ["W"]}):
            im = render.render(u, Image.new("RGB", (1216, 832), "#456"), t)
            assert im.size == (750, 1050)


def test_very_long_rules_text_still_fits_without_error():
    u = {**render.sample_unit(), "oracle_text": "Whenever a creature enters the battlefield under your control, draw a card. " * 14}
    assert render.render(u, None, render.get_template("classic")).size == (750, 1050)


def test_art_shape():
    assert render.art_shape(render.get_template("classic")) == "landscape"
    assert render.art_shape(render.get_template("fullart")) == "portrait"


def test_compose_always_includes_the_subjects_own_description():
    sub = {"name": "Sam", "tags": ["short red hair", "round glasses"], "sentence": "A man with short red hair and round glasses.", "count_tag": "1boy"}
    p = prompts.compose({"scene": "He raises a lantern.", "tags": ["fantasy", "night"]}, subjects=[sub], direction="watercolor", shape="landscape")
    assert p.startswith("masterpiece, best quality, 1boy") and "round glasses" in p and "watercolor" in p and "He raises a lantern." in p


def test_pdf_nine_per_page_with_cut_marks(tmp_path):
    cards = []
    for n in range(10):
        p = tmp_path / f"{n}.png"
        Image.new("RGB", (750, 1050), (n * 20, 50, 90)).save(p)
        cards.append(p)
    pages = export.sheets(cards, "letter")
    assert len(pages) == 2 and pages[0].size == (2550, 3300)
    pdf = export.pdf_bytes(cards, "a4")
    assert pdf.startswith(b"%PDF")


def test_mana_symbols_draw_their_icon_from_the_mana_font():
    tpl = render.get_template("classic")
    for sym in ("W", "U", "B", "R", "G", "C", "X", "2", "T", "W/U", "2/W", "W/P"):
        sheet = Image.new("RGB", (80, 80), "#ffffff")
        render.pip(sheet, tpl, sym, 8, 8, 64)
        dark = sum(1 for px in sheet.convert("L").crop((16, 16, 64, 64)).getdata() if px < 90)
        assert dark > 60, f"{sym}: no icon was drawn"


def test_blank_margins_around_generated_art_are_trimmed():
    from PIL import ImageDraw
    im = Image.new("RGB", (832, 1216), "white")
    ImageDraw.Draw(im).rectangle((300, 0, 560, 1215), fill=(120, 30, 30))
    t = render.trim_margins(im)
    assert t.width < 270 and t.height > 1200
    plain = Image.new("RGB", (400, 400), (90, 120, 160))
    assert render.trim_margins(plain).size == (400, 400)
