"""AI answers as one more piece of evidence. Never touches files.

- The AI agrees with SortZen: the percentage rises, halfway towards 100 at most, scaled by
  how sure the AI was (never above 97).
- The AI alone: its choice counts for at most 70%, so at the usual autonomy level it waits in
  Review. It replaces SortZen's own guess only when that guess was less sure.
- Files users placed themselves are never changed.
"""
from __future__ import annotations

import os

from .plan import Plan, Reason

AI_ALONE_MAX = 70
AGREE_MAX = 97


def apply_ai(plan: Plan, answers: dict, is_valid, names: dict[str, str] | None = None) -> int:
    """Use remembered answers (path -> AIAnswer) on the plan's files. Returns how many files they changed.

    ``names`` maps each service's key to the name shown in the reasons, e.g. "gemini" -> "Gemini".
    """
    changed = 0
    for s in plan.files:
        a = answers.get(s.path)
        if a is None or s.percent >= 100:
            continue
        service_name = (names or {}).get(a.service, "The AI service")
        why = f": {a.why}" if a.why else ""
        if a.destination is None or not is_valid(a.destination):
            if a.destination is None:
                s.reasons.append(Reason(False, f"{service_name} found no folder that fits"))
            continue
        if s.destination and os.path.normcase(a.destination) == os.path.normcase(s.destination):
            before = s.percent
            s.percent = min(AGREE_MAX, round(s.percent + (100 - s.percent) * 0.5 * a.sure / 100))
            s.reasons.insert(0, Reason(True, f"{service_name} also chose this folder ({a.sure}% sure){why}"))
            changed += s.percent != before
            continue
        alone = round(a.sure * AI_ALONE_MAX / 100)
        if alone > s.percent:
            own = (f"SortZen's own best guess was “{os.path.basename(s.destination)}” ({s.percent}%)"
                   if s.destination else "SortZen couldn't place it by itself")
            s.runner_up = (s.destination, s.percent) if s.destination else None
            s.destination, s.percent = a.destination, alone
            s.new_folder = not os.path.isdir(a.destination)
            s.reasons = [Reason(True, f"{service_name} chose this folder ({a.sure}% sure){why}"), Reason(False, own),
                         Reason(False, f"An AI answer alone counts for at most {AI_ALONE_MAX}%")]
            changed += 1
        else:
            s.reasons.append(Reason(False, f"{service_name} suggested “{os.path.basename(a.destination)}” instead "
                                           f"({a.sure}% sure)"))
    return changed
