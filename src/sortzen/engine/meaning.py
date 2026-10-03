"""Matching by meaning as one more piece of evidence. Never touches files.

Each folder that can receive files has a meaning profile: the average meaning of its files, its
name and its note. A file SortZen isn't sure about is compared with every profile:
- when the closest folder is the one SortZen already suggests, the percentage rises (up to 95);
- when SortZen had no good suggestion and one folder is clearly closest, that folder is
  suggested, at 65% at most, so it waits in Review.
Files users placed themselves, files placed by rules and topic members keep what they have.
"""
from __future__ import annotations

import os

from .plan import Plan, Reason

AGREE_SIMILARITY = 0.50         # the closest folder agrees with SortZen at least this closely
ALONE_SIMILARITY = 0.60         # a folder suggested by meaning alone is at least this close
MARGIN = 0.05                   # ...and this much closer than the next folder
ALONE_MAX = 65
AGREE_GAIN = 0.3                # share of the way to 100 an agreeing match adds
AGREE_MAX = 95
NAME_WEIGHT = 0.5               # a folder's name, against the average of its files
NOTE_WEIGHT = 1.0


def profiles(np, folders: list[str], member_rows: dict[str, list[int]], file_vectors, name_vectors, note_vectors):
    """One row per folder: its files' average meaning plus its name and note, scaled to length 1."""
    rows = np.zeros((len(folders), file_vectors.shape[1] if len(file_vectors) else name_vectors.shape[1]),
                    dtype=np.float32)
    for k, folder in enumerate(folders):
        members = member_rows.get(folder, [])
        if members:
            rows[k] = file_vectors[members].mean(axis=0)
        rows[k] += NAME_WEIGHT * name_vectors[k] + NOTE_WEIGHT * note_vectors[k]
    lengths = np.linalg.norm(rows, axis=1, keepdims=True)
    return np.divide(rows, lengths, out=np.zeros_like(rows), where=lengths > 0)


def apply_meaning(np, plan: Plan, vectors: dict, folders: list[str], matrix, display=lambda p: p) -> int:
    """Use meaning for the plan's unsure files (``vectors``: path -> the file's meaning). Returns files changed."""
    if not folders:
        return 0
    changed = 0
    for s in plan.files:
        vector = vectors.get(s.path)
        if vector is None or s.percent >= 100 or s.topic or not vector.any():
            continue
        sims = matrix @ vector
        order = np.argsort(-sims)
        best, sim = folders[order[0]], float(sims[order[0]])
        margin = sim - (float(sims[order[1]]) if len(order) > 1 else 0.0)
        if os.path.normcase(best) == os.path.normcase(os.path.dirname(s.path)):
            continue
        name = os.path.basename(best)
        if s.destination and os.path.normcase(best) == os.path.normcase(s.destination):
            if sim >= AGREE_SIMILARITY and margin >= MARGIN:
                before = s.percent
                s.percent = min(AGREE_MAX, round(s.percent + (100 - s.percent) * AGREE_GAIN))
                s.reasons.insert(0, Reason(True, f"By meaning, most like what is in “{name}”"))
                changed += s.percent != before
            continue
        if sim >= ALONE_SIMILARITY and margin >= MARGIN and (s.destination is None or s.percent < ALONE_MAX):
            alone = min(ALONE_MAX, round(sim * 100))
            if alone <= s.percent:
                continue
            own = (f"SortZen's own best guess was “{os.path.basename(s.destination)}” ({s.percent}%)"
                   if s.destination else "No folder's files share its words")
            s.runner_up = (s.destination, s.percent) if s.destination else None
            s.destination, s.percent = best, alone
            s.new_folder = not os.path.isdir(best)
            s.reasons = [Reason(True, f"By meaning, most like what is in “{name}” ({display(best)})"),
                         Reason(False, own), Reason(False, f"Meaning alone counts for at most {ALONE_MAX}%")]
            changed += 1
    return changed
