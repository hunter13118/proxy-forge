"""Pack a deck's rendered cards onto printable sheets without the web page:

    python scripts/print_sheets.py DECK_ID_OR_NAME [out.pdf] [--paper a4|letter] [--size mtg|inch] [--margin 5] [--gap 0] [--turn auto|never|always] [--no-marks] [--skip-basics] [--no-copies]

Prints to scale: open the PDF and print at 100% ("actual size"), never "fit to page". Cards come from the deck's current renders (a card without art is drawn as the template shows it).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from proxy_forge import export, store  # noqa: E402
from proxy_forge.engine import Engine  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("deck", help="deck id or name")
ap.add_argument("out", nargs="?", help="output PDF (default: <deck>-<paper>.pdf)")
ap.add_argument("--paper", default="a4", choices=sorted(export.PAPER))
ap.add_argument("--size", default="mtg", choices=sorted(export.CARD_MM), help="mtg = 63 x 88 mm (a real card), inch = 2.5 x 3.5 in")
ap.add_argument("--margin", type=float, default=5.0, help="unprintable border in mm")
ap.add_argument("--gap", type=float, default=0.0, help="space between cards in mm (0: shared cut lines)")
ap.add_argument("--turn", default="auto", choices=("auto", "never", "always"))
ap.add_argument("--no-marks", action="store_true")
ap.add_argument("--skip-basics", action="store_true")
ap.add_argument("--no-copies", action="store_true", help="one of each card, ignoring the copy counts")
a = ap.parse_args()

deck = next((d for d in store.list_decks() if a.deck in (d["id"], d["name"])), None)
if not deck:
    sys.exit(f"no deck {a.deck!r}; have: " + ", ".join(f"{d['id']} ({d['name']})" for d in store.list_decks()))
imgs = [p for _, p in Engine().card_images(deck["id"], not a.no_copies, a.skip_basics)]
if not imgs:
    sys.exit("no cards to print")
lay = export.best_layout(a.paper, a.size, a.margin, a.gap, a.turn)
out = Path(a.out or f"{deck['name']}-{a.paper}.pdf")
out.write_bytes(export.pdf_bytes(imgs, a.paper, size=a.size, margin_mm=a.margin, gap_mm=a.gap, turn=a.turn, marks=not a.no_marks))
print(f"{len(imgs)} cards -> {-(-len(imgs) // lay.per_page)} sheets of {lay.cols}x{lay.rows}{' (turned)' if lay.turned else ''} -> {out}")
