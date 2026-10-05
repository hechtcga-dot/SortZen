"""Run the engine on the test folders and grade it against the answer key.

    python -m tests.engine_score            # print the score and the mistakes
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from sortzen.engine import Planner, Source
from sortzen.engine.planner import SORT_OUT, TIDY
from sortzen.repositories.file_index import FileIndex
from sortzen.scanning.scanner import Scanner

AUTONOMY = 90


def run_engine(root: Path, key: dict | None = None, answers: dict | None = None):
    """Plan each test scenario on its own: Downloads into Sorted, and My Drive tidied in place."""
    with tempfile.TemporaryDirectory() as data:
        scanner = Scanner(FileIndex(Path(data) / "index.db"), protected=[])
        downloads = scanner.scan(root / "Downloads", "source", recursive=True).files
        drive = scanner.scan(root / "My Drive", "source", recursive=True).files
        sorted_ = scanner.scan(root / "Sorted", "destination", recursive=True).files
    first = Planner(downloads + sorted_, [Source(str(root / "Downloads"), SORT_OUT)], [str(root / "Sorted")],
                    answers=answers).plan()
    second = Planner(drive, [Source(str(root / "My Drive"), TIDY)], [], answers=answers).plan()
    for part in ("files", "folders", "topics", "questions", "new_folders"):
        getattr(first, part).extend(getattr(second, part))
    return first


def _rel(root: Path, path: str | None) -> str | None:
    return None if path is None else Path(os.path.relpath(path, root)).as_posix()


def score(plan, key: dict, root: Path, autonomy: int = AUTONOMY) -> dict:
    by_rel = {_rel(root, s.path): s for s in plan.files}
    placed = correct = ready = ready_right = review_total = review_held = 0
    stay_total = wrong_moves_out = 0
    misplaced_total = misplaced_found = 0
    organised = [f for f, o in key["folders"].items() if o == "stays"]
    buckets = {b: [0, 0] for b in (90, 70, 50, 0)}
    mistakes = []
    for rel, expected in key["files"].items():
        s = by_rel.get(rel)
        if s is None:
            mistakes.append((rel, "not in plan", expected, None, 0))
            continue
        if isinstance(expected, str) and expected.startswith("together: "):
            continue
        predicted = _rel(root, s.destination)
        is_ready = s.ready(autonomy)
        if expected is None:
            review_total += 1
            held = not is_ready or s.action == "stay"       # staying put moves nothing
            review_held += held
            if not held:
                ready += 1
                mistakes.append((rel, "should be Review", expected, predicted, s.percent))
            continue
        placed += 1
        right = predicted == expected
        correct += right
        bucket = next(b for b in buckets if s.percent >= b)
        buckets[bucket][0] += 1
        buckets[bucket][1] += right
        if expected != rel.rsplit("/", 1)[0] and any(rel.startswith(f + "/") for f in organised):
            misplaced_total += 1
            misplaced_found += s.action == "move"
        if expected == rel.rsplit("/", 1)[0]:
            stay_total += 1
            if is_ready and not right:
                wrong_moves_out += 1
        if is_ready:
            ready += 1
            ready_right += right
        if not right:
            mistakes.append((rel, "wrong folder", expected, predicted, s.percent))
    folders_right, folder_mistakes, kept_total, kept_right = 0, [], 0, 0
    planned_folders = {_rel(root, f.path): f for f in plan.folders}
    judged = {f: o for f, o in key["folders"].items() if not o.startswith("together: ")}
    for folder, expected in judged.items():
        f = planned_folders.get(folder)
        got = f.outcome if f else "stays"
        want = expected.split(":")[0]
        right = got == want
        if want == "keep together":
            kept_total += 1
            kept_right += right and _rel(root, f.destination) == expected.split(": ", 1)[1]
        folders_right += right
        if not right:
            folder_mistakes.append((folder, want, got))
    topics_ok = []
    for topic, members in key.get("topics", {}).items():
        places = set()
        for m in members:
            f, s = planned_folders.get(m), by_rel.get(m)
            if f:
                places.add(_rel(root, f.destination) if f.destination else m)
            elif s:
                places.add(_rel(root, s.destination or s.current_folder))
        asked = any(len({_rel(root, a) for a in q.about} & set(members)) >= len(members) / 2 for q in plan.questions)
        topics_ok.append(len(places) == 1 or asked)
    return {
        "folders decided right": f"{folders_right} of {len(judged)}",
        "kept-together folders placed right": f"{kept_right} of {kept_total}",
        "topics together or asked about": f"{sum(topics_ok)} of {len(topics_ok)}",
        "questions": len(plan.questions),
        "files with a right answer": placed,
        "top suggestion right": correct / placed,
        "ready (at or above autonomy)": ready,
        "ready and right": ready_right / ready if ready else 1.0,
        "share placed without asking": ready_right / placed,
        "review-only files kept for review": review_held / review_total if review_total else 1.0,
        "wrong moves out of organised folders": wrong_moves_out,
        "files that should stay": stay_total,
        "misplaced files found": f"{misplaced_found} of {misplaced_total}",
        "right, by percentage band": {f"{b}%+": (n, round(r / n, 2) if n else None) for b, (n, r) in buckets.items()},
        "mistakes": sorted(mistakes, key=lambda m: -m[4]),
        "folder mistakes": folder_mistakes,
        "question texts": [q.text for q in plan.questions],
    }


def main() -> None:
    from tests.fixtures import answer_key, shared_test_folders

    root = shared_test_folders()
    key = answer_key()
    result = score(run_engine(root), key, root)
    for name, value in result.items():
        if name not in ("mistakes", "folder mistakes", "question texts"):
            print(f"{name:40} {value if not isinstance(value, float) else f'{value:.1%}'}")
    print("\nFolder mistakes (folder, expected, got):")
    for m in result["folder mistakes"]:
        print("   ", m)
    print("\nQuestions:")
    for q in result["question texts"]:
        print("   ", q)
    print("\nMistakes (highest percentage first):")
    for rel, kind, expected, predicted, percent in result["mistakes"][: int(sys.argv[1]) if len(sys.argv) > 1 else 40]:
        print(f"{percent:3d}%  {kind:16} {rel}\n        expected {expected}\n        got      {predicted}")


if __name__ == "__main__":
    main()
