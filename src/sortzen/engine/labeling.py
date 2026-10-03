"""Labels: what users call their files ("Work", "Taxes", "Photo session"). Never touches files.

- ``guess_labels`` labels files on the PC: from a label's words in a file's name, its folders,
  its contents or a note users wrote about it, and from the labelled files most like it.
- ``label_evidence`` uses labels as evidence for a file's folder. Each folder's labels come
  from the labelled files in it (files users put there count most), and a file's labels count
  by their priority: the label at the top of users' list counts most.
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict

from .features import clues_for, finish_vectors, rarity, words
from .plan import Plan, Reason
from .planner import _Index

NEIGHBOURS = 7
SHOWN_FROM = 30             # labels guessed below this percentage are not kept
WORD_IN_NOTE = 0.9          # how sure a label's word makes it, by where the word is found
WORD_IN_NAME = 0.85
WORD_IN_FOLDER = 0.7
WORD_IN_CONTENTS = 0.4       # alone, too little to apply a label: one mention in a letterhead says little
GUESS_MAX = 97
PRIORITY_LOWEST = 0.5       # the bottom label counts this much of the top one
FOLDER_SHARE = 0.5          # a folder must hold labels like the file's at least this much to count
EVIDENCE_MAX = 95
LEAN_FROM = 60              # an unsure file (no folder, or under this) leans towards its labels' folder
USERS_PLACED_WEIGHT = 3.0   # a file users put in a folder counts this many times for the folder's labels


def label_words(label: str) -> set[str]:
    return set(words(label))


def _word_score(wanted: set[str], places: list[tuple[set[str], float]]) -> tuple[float, str]:
    """How well a label's words are found: each word by the best place it is in, all words together."""
    if not wanted:
        return 0.0, ""
    total, where = 0.0, ""
    for w in wanted:
        best = max(((score, name) for found, score, name in places if w in found), default=(0.0, ""))
        total += best[0]
        where = where or best[1]
    return total / len(wanted), where


def guess_labels(records: list, labels: list[str], known: dict[str, list[str]],
                 notes: dict[str, str] | None = None) -> dict[str, list[tuple[str, int, str]]]:
    """Labels for the files not in ``known`` (labels users or the AI gave, by path): (label, percent, why),
    surest first."""
    if not labels or not records:
        return {}
    notes = {os.path.normcase(k): v for k, v in (notes or {}).items()}
    clues = [clues_for(r) for r in records]
    finish_vectors(clues, rarity(clues))
    by_key = {os.path.normcase(k): v for k, v in known.items()}
    examples = [i for i, r in enumerate(records) if by_key.get(os.path.normcase(r.path))]
    index = _Index([clues[i].vector for i in examples]) if examples else None
    wanted = {label: label_words(label) for label in labels}
    found: dict[str, list[tuple[str, int, str]]] = {}
    for i, r in enumerate(records):
        if by_key.get(os.path.normcase(r.path)):
            continue
        parts = os.path.normpath(os.path.dirname(r.path)).split(os.sep)[-3:]
        places = [(set(clues[i].name_words), WORD_IN_NAME, "its name"),
                  (set(words(" ".join(parts))), WORD_IN_FOLDER, "its folder"),
                  (set(clues[i].content_words), WORD_IN_CONTENTS, "its contents")]
        note = notes.get(os.path.normcase(r.path))
        if note:
            places.insert(0, (set(words(note)), WORD_IN_NOTE, "your note"))
        votes: dict[str, float] = defaultdict(float)
        like: dict[str, str] = {}
        if index is not None:
            near = index.search(clues[i].vector)[:NEIGHBOURS]
            weight = sum(sim for _, sim in near) or 1.0
            closeness = min(1.0, (near[0][1] if near else 0.0) / 0.5)
            for pos, sim in near:
                other = records[examples[pos]]
                for label in by_key[os.path.normcase(other.path)]:
                    votes[label] += sim / weight * closeness
                    like.setdefault(label, other.name)
        guesses = []
        for label in labels:
            word, where = _word_score(wanted[label], places)
            vote = min(1.0, votes.get(label, 0.0))
            percent = round(min(GUESS_MAX, 100 * (1 - (1 - word) * (1 - 0.95 * vote))))
            if percent < SHOWN_FROM:
                continue
            why = f"“{label}” is in {where}" if word >= vote and where else f"Like “{like.get(label, '')}”"
            guesses.append((label, percent, why))
        if guesses:
            found[r.path] = sorted(guesses, key=lambda g: -g[1])
    return found


def priority_weights(labels: list[str]) -> dict[str, float]:
    """How much each label counts: the top label 1.0, down to PRIORITY_LOWEST for the bottom one."""
    n = len(labels)
    return {label: 1.0 - (1.0 - PRIORITY_LOWEST) * (i / (n - 1) if n > 1 else 0.0) for i, label in enumerate(labels)}


def folder_labels(file_labels: dict[str, list[tuple[str, int]]], placed: dict[str, str]) -> dict[str, Counter]:
    """Each folder's labels: from the labelled files in it, and the files users put there (``placed``:
    file -> folder) counting more."""
    found: dict[str, Counter] = defaultdict(Counter)
    placed_keys = {os.path.normcase(k): v for k, v in placed.items()}
    for path, labels in file_labels.items():
        chosen = placed_keys.get(os.path.normcase(path))
        folder = chosen or os.path.dirname(path)
        weight = USERS_PLACED_WEIGHT if chosen else 1.0
        for label, percent in labels:
            found[os.path.normcase(folder)][label] += weight * percent / 100
        found[os.path.normcase(folder)][""] += weight          # how many files it has, labelled or not
    return found


def label_evidence(plan: Plan, file_labels: dict[str, list[tuple[str, int]]], profiles: dict[str, Counter],
                   order: list[str], display, keep=lambda path: False, folders=None) -> int:
    """Labels as evidence for files' folders. ``profiles`` from folder_labels; ``order``: labels, top first;
    ``folders``: the folders files may go to (by normcase path) and their paths. Returns how many changed."""
    weights = priority_weights(order)
    labels_by_key = {os.path.normcase(k): v for k, v in file_labels.items()}
    candidates = {k: v for k, v in profiles.items() if v[""] >= 2 and (folders is None or k in folders)}
    changed = 0
    for s in plan.files:
        mine = labels_by_key.get(os.path.normcase(s.path))
        if not mine or keep(s.path) or s.percent >= 100:
            continue
        wanted = {label: weights.get(label, PRIORITY_LOWEST) * percent / 100 for label, percent in mine}
        total = sum(wanted.values())
        if not total:
            continue
        best, best_score = None, 0.0
        for key, counts in candidates.items():
            if key == os.path.normcase(s.current_folder):
                continue
            files = counts[""]
            score = sum(w * min(1.0, counts.get(label, 0.0) / files) for label, w in wanted.items()) / total
            if score > best_score:
                best, best_score = key, score
        if best is None or best_score < FOLDER_SHARE:
            continue
        target = folders[best] if folders else best
        top = max(mine, key=lambda m: weights.get(m[0], 0) * m[1])[0]
        reason = Reason(True, f"Labelled “{top}”, like most files in {display(target)}")
        sureness = sum(percent for _, percent in mine) / len(mine) / 100
        if s.destination and os.path.normcase(s.destination) == os.path.normcase(target):
            s.percent = min(EVIDENCE_MAX, s.percent + round((100 - s.percent) * best_score * sureness / 2))
        elif s.destination is None or s.percent < LEAN_FROM:
            if s.destination:
                s.runner_up = (s.destination, s.percent)
            s.destination = target
            s.percent = min(EVIDENCE_MAX, round(50 + 45 * best_score * sureness))
            s.new_folder = not os.path.isdir(target)
        else:
            continue
        s.reasons.insert(0, reason)
        changed += 1
    return changed


LABEL_RULE_EXAMPLES = 3     # files with one label users put in the same folder before a rule is suggested


def suggest_label_rule(examples: list[list[str]], destination: str, others: list[tuple[str, str | None, int, list[str]]],
                       rules: list, declined: set[str]):
    """A rule "files labelled X go to this folder" when users put several files with that label there.

    ``examples``: the labels of each file users put there; ``others``: the plan's other files as (path,
    destination, percent, labels). Suggested only when it would place other files, never moving one
    SortZen is sure belongs elsewhere."""
    from .rules import SURE_ELSEWHERE, Rule, RuleSuggestion

    counts = Counter(label for labels in examples for label in set(labels))
    known = {r.key for r in rules} | set(declined)
    best = None
    for label, count in counts.most_common():
        if count < LABEL_RULE_EXAMPLES or count < 0.8 * len(examples):
            continue
        rule = Rule("", destination, label=label)
        if rule.key in known:
            continue
        gain, harm = [], 0
        for path, current, percent, labels in others:
            if label not in labels or (current and os.path.normcase(current) == os.path.normcase(destination)):
                continue
            if current and percent >= SURE_ELSEWHERE:
                harm += 1
            else:
                gain.append(path)
        if gain and not harm and (best is None or count > best.examples):
            best = RuleSuggestion(rule, count, gain)
    return best


HOME_SHARE = 0.5            # a folder is a label's home when this share of its files carry the label
HOME_FILES = 3


def label_homes(profiles: dict[str, Counter], labels: list[str]) -> dict[str, tuple[str, float]]:
    """Each label's home folder (by normcase path), when one holds mostly files with that label: (folder, share)."""
    homes = {}
    for label in labels:
        best = None
        for key, counts in profiles.items():
            files, have = counts[""], counts.get(label, 0.0)
            if files >= HOME_FILES and have >= HOME_FILES * 0.7 and have / files >= HOME_SHARE:
                if best is None or have > best[2]:
                    best = (key, have / files, have)
        if best:
            homes[label] = (best[0], best[1])
    return homes
