"""Grade matching by meaning on the test folders: meaning off, then on at several settings.

    python -m tests.meaning_score       # needs the meaning model (packaging/get_meaning_model.py)
"""
from __future__ import annotations

import itertools
import os
import tempfile
from pathlib import Path

from sortzen.config import AppPaths
from sortzen.engine import meaning
from sortzen.engine.planner import TIDY
from sortzen.repositories.api_keys import ApiKeyStore
from sortzen.services import AppService
from tests.engine_score import _rel, score
from tests.test_repositories import FakeKeyring


def plans(root: Path, on: bool):
    """Downloads into Sorted, and My Drive tidied in place, each planned on its own (as the engine score does)."""
    found = []
    for sources, destinations in (([(root / "Downloads", "sort into other folders")], [root / "Sorted"]),
                                  ([(root / "My Drive", TIDY)], [])):
        data = tempfile.mkdtemp()
        service = AppService(AppPaths(Path(data)), ApiKeyStore(FakeKeyring()))
        service.scanner.protected = []
        service.set_option("meaning", on)
        for path, mode in sources:
            service.add_source(str(path), mode)
        for path in destinations:
            service.add_destination(str(path))
        found.append(service.make_plan())
    first, second = found
    for part in ("files", "folders", "topics", "questions", "new_folders"):
        getattr(first, part).extend(getattr(second, part))
    return first


def line(name, result, plan, key, root) -> str:
    alone = [s for s in plan.files if any(r.text.startswith("Meaning alone") for r in s.reasons)]
    agree = [s for s in plan.files if any(r.text.startswith("By meaning") for r in s.reasons) and s not in alone]
    expected = key["files"]

    def right(s):
        want = expected.get(_rel(root, s.path), "?")
        return want == _rel(root, s.destination)

    return (f"{name:34} top {result['top suggestion right']:.1%}  ready {result['ready (at or above autonomy)']:4}"
            f"  ready right {result['ready and right']:.1%}  placed {result['share placed without asking']:.1%}"
            f"  held {result['review-only files kept for review']:.0%}  alone {sum(map(right, alone))}/{len(alone)}"
            f"  agree {sum(map(right, agree))}/{len(agree)}")


def main() -> None:
    from tests.fixtures import answer_key, shared_test_folders

    root, key = shared_test_folders(), answer_key()
    print(line("meaning off", score(plans(root, False), key, root), plans(root, False), key, root))
    for agree, alone, margin in itertools.product((0.40, 0.50, 0.60), (0.50, 0.60, 0.70), (0.03, 0.08)):
        meaning.AGREE_SIMILARITY, meaning.ALONE_SIMILARITY, meaning.MARGIN = agree, alone, margin
        plan = plans(root, True)
        print(line(f"agree {agree} alone {alone} margin {margin}", score(plan, key, root), plan, key, root))
    meaning.AGREE_SIMILARITY, meaning.ALONE_SIMILARITY, meaning.MARGIN = 0.5, 0.6, 0.05
    plan = plans(root, True)
    print("\nMeaning-alone examples (file, expected, got, sure):")
    for s in [s for s in plan.files if any(r.text.startswith("Meaning alone") for r in s.reasons)][:15]:
        print("   ", _rel(root, s.path), "|", key["files"].get(_rel(root, s.path)), "|", _rel(root, s.destination),
              "|", s.percent)
    texts = ["pay stub for March", "Payroll", "lemon tart recipe", "Recipes", "dentist appointment", "Health"]
    from sortzen import meaning as model
    m = model.load()
    v = m.embed(texts)
    print("\nSimilarities:", {f"{texts[i]}~{texts[j]}": round(float(v[i] @ v[j]), 2)
                              for i, j in ((0, 1), (0, 3), (2, 3), (2, 1), (4, 5), (4, 1))})


if __name__ == "__main__":
    main()
