"""Files users said are similar to, or different from, another file: evidence, never a move.

"Similar to" counts for the folder the other file is in (or is planned to go to): a suggestion
that agrees gets surer, an unsure file leans towards it, and a sure suggestion elsewhere gets
less sure. "Different from" counts against that folder. Choices users made themselves (a folder
they chose, a rule) are left as they are.
"""
from __future__ import annotations

import os

from .plan import Plan, Reason

SIMILAR_MAX = 95            # an agreeing "similar to" raises the percentage halfway towards 100, at most this
SIMILAR_ALONE = 60          # an unsure file leans towards the similar file's folder, still waiting for users
SIMILAR_DOUBT = 0.8         # a suggestion elsewhere keeps this share of its percentage
DIFFERENT_MAX = 30          # a suggestion for the folder of a file it differs from drops to at most this


def apply_pairs(plan: Plan, similar: list[tuple[str, str]], different: list[tuple[str, str]],
                home_of, display, keep=lambda path: False) -> int:
    """Use (file, other file) pairs as evidence. ``home_of(other)`` is the folder the other file is in or
    is headed for; ``keep(path)`` marks files whose folder users chose. Returns how many changed."""
    by_path = {os.path.normcase(s.path): s for s in plan.files}
    changed = 0
    for path, other in similar:
        s = by_path.get(os.path.normcase(path))
        target = home_of(other)
        if s is None or not target or keep(s.path) or s.percent >= 100:
            continue
        reason = Reason(True, f"You said it's like “{os.path.basename(other)}” (in {display(target)})")
        if s.destination and os.path.normcase(s.destination) == os.path.normcase(target):
            s.percent = min(SIMILAR_MAX, max(s.percent, s.percent + (100 - s.percent) // 2))
        elif s.destination is None or s.percent < SIMILAR_ALONE:
            if s.destination:
                s.runner_up = (s.destination, s.percent)
            s.destination, s.percent = target, SIMILAR_ALONE
            s.new_folder = not os.path.isdir(target)
        else:
            s.runner_up = (target, SIMILAR_ALONE)
            s.percent = int(s.percent * SIMILAR_DOUBT)
            reason = Reason(False, f"You said it's like “{os.path.basename(other)}”, which is in {display(target)}")
        s.reasons.insert(0, reason)
        changed += 1
    for path, other in different:
        s = by_path.get(os.path.normcase(path))
        target = home_of(other)
        if s is None or not target or keep(s.path) or s.percent >= 100 or not s.destination:
            continue
        if os.path.normcase(s.destination) != os.path.normcase(target):
            continue
        reason = Reason(False, f"You said it's different from “{os.path.basename(other)}” (in {display(target)})")
        runner = s.runner_up
        if runner and runner[0] and os.path.normcase(runner[0]) != os.path.normcase(target):
            s.runner_up = (s.destination, min(s.percent, DIFFERENT_MAX))
            s.destination, s.percent = runner[0], min(runner[1], SIMILAR_ALONE)
            s.new_folder = not os.path.isdir(s.destination)
        else:
            s.percent = min(s.percent, DIFFERENT_MAX)
        s.reasons.insert(0, reason)
        changed += 1
    return changed
