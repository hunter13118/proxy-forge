"""Skipped unless `pytest -m live`: builds the real printings index and resolves a real deck list against it (network, ~80 MB). Records the timing for the plan's first goal."""
import time

import pytest

from proxy_forge import resolver
from proxy_forge.printings import Printings

pytestmark = pytest.mark.live


def test_real_index_and_a_hundred_cards(tmp_path):
    p = Printings(tmp_path / "live.sqlite")
    t = time.time()
    p.build()
    built = time.time() - t
    names = ["Sol Ring", "Arcane Signet", "Command Tower", "Counterspell", "Lightning Bolt", "Island", "Forest", "Swords to Plowshares"] * 12
    t = time.time()
    ids = p.oracle_ids(names)
    assert all(ids.values())
    cov = p.coverage(list(ids.values()))
    picks = [resolver.resolve_unit(p, {"oracle_id": o, "name": n, "type_line": ""}, {**resolver.DEFAULT_POLICY, "source": "archive", "sets": ["cmm"]}) for n, o in ids.items()]
    print(f"\nindex {built:.0f}s, 96 cards resolved in {time.time() - t:.2f}s, best set {list(cov.items())[0]}")
    assert time.time() - t < 1 and sum(1 for r in picks if r.get("printing") and r["printing"]["set_code"] == "cmm") >= 6
