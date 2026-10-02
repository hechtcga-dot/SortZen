"""The overview: what each subfolder is, topics spread over several places, and questions.

A subfolder of a source folder is judged from its name (generic names like "older
downloads" are messy; "To e-mail" and restored drives are for users to decide), from a
.zip of the same name beside it (an unzipped download), from how many of its files mention
the folder's own name, and from where its files would go if the folder weren't there:
files that clearly belong in several different folders elsewhere make it messy.

A topic is a rare word (or words) shared by the names of files and folders in several
places, such as "Garden Planner" in My Drive, in a relative's folder and in Projects.
Each topic gets a home and a question; members wait in Review until it is answered.
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict

from ..repositories.file_index import path_key
from .features import DEFAULT_NAME_WORDS, words
from .plan import (FOLDER_REVIEW, KEEP_TOGETHER, SORT_INSIDE, STAYS, Choice, FolderSuggestion, Plan, Question,
                   Reason, Topic)

MESSY_WORDS = {"unsorted", "misc", "miscellaneou", "miscellaneous", "stuff", "temp", "tmp", "old", "older", "random",
               "various", "dump", "download", "inbox", "unfiled", "junk"}
HOLDING_PREFIXES = ("to ", "for ")          # "To e-mail", "To print", "For review"
HOLDING_WORDS = {"restored", "pending"}
COPY_WORDS = {"window", "windows", "release", "copy", "backup", "final", "old", "new", "version"}
GENERIC_TOPIC_WORDS = {"drive", "onedrive", "google", "sorted", "folder", "file", "scan", "screenshot", "image",
                       "photo", "picture", "document", "report", "statement", "receipt", "invoice", "resume", "letter",
                       "form", "template", "note", "list", "draft", "update", "updated", "personal", "work"}
MAX_QUESTIONS = 10
PROGRAM_MARKERS = {"setup.py", "pyproject.toml", "requirements.txt", "requirements-dev.txt", "package.json",
                   "cargo.toml", "go.mod", "pom.xml", "build.gradle", "cmakelists.txt", "makefile", "gemfile",
                   "composer.json"}
PROGRAM_MARKER_EXTS = {".sln", ".csproj", ".vcxproj", ".spec", ".iss"}
CODE_EXTS = {".py", ".pyw", ".js", ".ts", ".jsx", ".tsx", ".java", ".cs", ".cpp", ".cc", ".c", ".h", ".hpp", ".go",
             ".rs", ".rb", ".php", ".swift", ".kt", ".ipynb", ".vb", ".lua", ".dart"}
CODE_SHARE = 0.4            # share of code files that makes a folder a program
FAMILY_PERCENT = 90         # versions and copies of one thing, gathered into one folder
_COPY_END = re.compile(r"\s*\(\d+\)$")
_VERSION_END = re.compile(r"[-_ .]+v?\d+(?:\.\d+)*[a-z]?$", re.I)
_EDITION_END = re.compile(r"[-_ ]+(?:release|windows|win|win32|win64|x64|x86|amd64|portable|setup|installer|"
                          r"final|copy|backup|old|new|latest|master|main|build|dist|stable|beta|alpha)$", re.I)
CLEAR_HOME = 70             # a file this sure of a folder elsewhere has a clear home there
MESSY_SHARE = 0.6           # share of a folder's files with clear homes elsewhere that makes it messy
NAME_SHARE = 0.5            # share of files mentioning the folder's name that keeps it together
CLOSE_KNIT = 0.6            # share of files most like each other that keeps a folder together
MIN_FILES = 4               # fewer files than this: a tidy folder is never called messy
SAMPLE = 60                 # files per folder looked at in detail
TOPIC_NAME_SHARE = 0.15     # a topic word appears in the names of at most this share of items
TOPIC_WAIT_PERCENT = 70     # topic members wait in Review until the question is answered


def _inside(path: str, folder: str) -> bool:
    key, root = path_key(path), path_key(folder)
    return key == root or key.startswith(root.rstrip(os.sep) + os.sep)


def folder_key(folder: str) -> str:
    return f"folder:{path_key(folder)}"


def topic_key(root: str, name: str) -> str:
    return f"topic:{path_key(root)}:{name.lower()}"


def _tree(p):
    children: dict[str, set[str]] = defaultdict(set)
    files_under: dict[str, list[int]] = defaultdict(list)
    for i, record in enumerate(p.records):
        source = p._source_of(record.path)
        if not source:
            continue
        folder = p.folder[i]
        while path_key(folder) != path_key(source.root) and _inside(folder, source.root):
            files_under[folder].append(i)
            parent = os.path.dirname(folder)
            children[parent].add(folder)
            folder = parent
    return children, files_under


def _folder_choices(mode: str) -> list[Choice]:
    from .planner import SORT_OUT

    choices = [Choice("Leave it as it is", None, STAYS), Choice("Sort its files one by one", None, SORT_INSIDE)]
    if mode == SORT_OUT:
        choices.append(Choice("Keep it together and move it", None, KEEP_TOGETHER))
    return choices


# ---------------------------------------------------------------- programs and families
def is_program(p, folder: str) -> str:
    """Why a folder is a program (code, setup files, or a built program with its parts); "" when it isn't."""
    files = [p.records[i] for i in p.files_under.get(folder, [])]
    if not files:
        return ""
    names = {r.name.lower() for r in files}
    exts = Counter(r.ext for r in files)
    marker = sorted(names & PROGRAM_MARKERS) or sorted(r.name for r in files if r.ext in PROGRAM_MARKER_EXTS)
    if marker:
        return f"Looks like a program: it has “{marker[0]}”"
    code = sum(n for e, n in exts.items() if e in CODE_EXTS)
    if code >= 5 and code >= CODE_SHARE * len(files):
        return f"Looks like a program: {code} of its {len(files)} files are code"
    if exts.get(".exe") and (exts.get(".dll") or exts.get(".pyd")):
        return "Looks like a program: a .exe with the parts it needs"
    return ""


def family_base(name: str, is_file: bool = False) -> str:
    """A name without version and copy endings: "AuctionZen-windows (4)" and "AuctionZen-1.7.3" give "AuctionZen"."""
    base = os.path.splitext(name)[0] if is_file else name
    while True:
        trimmed = _COPY_END.sub("", base)
        trimmed = _VERSION_END.sub("", trimmed)
        trimmed = _EDITION_END.sub("", trimmed).strip(" -_.")
        if trimmed == base or not trimmed:
            return base
        base = trimmed


def _family_key(name: str, is_file: bool = False) -> str:
    return re.sub(r"[^a-z0-9]", "", family_base(name, is_file).lower())


def gather_families(p, plan: Plan) -> dict[str, tuple[str, list[Reason]]]:
    """Sibling folders that are versions or copies of one thing go together into one new folder.

    Returns the zips and installers beside them that join their family: path -> (folder, reasons).
    """
    decided = {path_key(f.path): f for f in plan.folders}
    sorted_inside = [s.root for s in p.sources] + [f.path for f in plan.folders if f.outcome == SORT_INSIDE]
    joining: dict[str, tuple[str, list[Reason]]] = {}
    for parent in sorted_inside:
        groups: dict[str, list[str]] = defaultdict(list)
        for child in sorted(p.children.get(parent, ())):
            answered = folder_key(child) in p.answers
            if p.is_left_out(child) or answered or any(_inside(child, u) and path_key(child) != path_key(u)
                                                       for u in p.units):
                continue
            key = _family_key(os.path.basename(child))
            if len(key) >= 3:
                groups[key].append(child)
        taken = {os.path.basename(c).lower() for c in p.children.get(parent, ())}
        for key, members in groups.items():
            if len(members) < 2:
                continue
            base = family_base(min((os.path.basename(m) for m in members), key=len))
            program = next((why for m in members if (why := is_program(p, m))), "")
            name = f"{base} Program" if program else f"{base} (all copies)"
            n = 2
            while name.lower() in taken:
                name, n = f"{base} {'Program' if program else '(all copies)'} {n}", n + 1
            home = os.path.join(parent, name)
            why = [Reason(True, f"{len(members)} folders are versions or copies of “{base}”: "
                                f"{', '.join(os.path.basename(m) for m in members[:4])}"
                                + (" …" if len(members) > 4 else ""))]
            if program:
                why.append(Reason(True, program))
            for m in members:
                f = decided.get(path_key(m))
                if f is None:
                    f = FolderSuggestion(m, KEEP_TOGETHER, FAMILY_PERCENT, files=len(p.files_under[m]))
                    plan.folders.append(f)
                    decided[path_key(m)] = f
                f.outcome, f.destination, f.percent, f.reasons = KEEP_TOGETHER, home, FAMILY_PERCENT, list(why)
                p.units.add(m)
            plan.folders[:] = [f for f in plan.folders
                               if not any(_inside(f.path, m) and path_key(f.path) != path_key(m) for m in members)]
            for i in p.direct.get(parent, []):
                r = p.records[i]
                if r.kind in ("archive", "installer") and _family_key(r.name, True) == key:
                    joining[r.path] = (home, why[:1] + [Reason(True, f"“{r.name}” is part of the same family")])
            plan.new_folders.append(home)
    return joining


# ---------------------------------------------------------------- subfolders
def decide_folders(p) -> list[FolderSuggestion]:
    """Clear cases first (names, zips, shared names); then, in rounds, folders whose files clearly
    belong in several organised folders elsewhere, comparing only with folders not already found messy."""
    p.children, p.files_under = _tree(p)
    p.units = set()             # programs and families: always moved or left whole
    p.direct = defaultdict(list)
    for i, folder in enumerate(p.folder):
        p.direct[folder].append(i)
    decided: dict[str, FolderSuggestion] = {}
    pending: list[tuple[str, object]] = []

    def look(folder: str, source) -> None:
        if p.is_left_out(folder):
            return
        clear = _decide_clear(p, folder, source)
        if clear is None:
            pending.append((folder, source))
            return
        decided[folder] = clear
        if clear.outcome == SORT_INSIDE:
            for child in sorted(p.children[folder]):
                look(child, source)

    for source in p.sources:
        for child in sorted(p.children[source.root]):
            look(child, source)
    while pending:
        p.excluded = [f for f, d in decided.items() if d.outcome != STAYS]
        p._prepare()
        results = {folder: _decide_spread(p, folder, source) for folder, source in pending}
        messy = [(f, s) for f, s in pending if results[f].outcome == SORT_INSIDE]
        if not messy:
            decided.update(results)
            break
        pending = [(f, s) for f, s in pending if results[f].outcome != SORT_INSIDE]
        for folder, source in messy:
            decided[folder] = results[folder]
            for child in sorted(p.children[folder]):
                look(child, source)
    return list(decided.values())


def _result(folder, n, outcome, percent, *reasons) -> FolderSuggestion:
    return FolderSuggestion(folder, outcome, max(0, min(99, round(percent))), list(reasons), files=n)


def _decide_clear(p, folder: str, source) -> FolderSuggestion | None:
    """Folders whose name, answer or neighbouring zip settles them; None when it takes a closer look."""
    from .planner import SORT_OUT

    files = p.files_under[folder]
    n = len(files)
    name = os.path.basename(folder)
    name_words = words(name)
    keep = KEEP_TOGETHER if source.mode == SORT_OUT else STAYS

    def result(outcome, percent, *reasons):
        return _result(folder, n, outcome, percent, *reasons)

    answer = p.answers.get(folder_key(folder))
    choices = _folder_choices(source.mode)
    if answer is not None and 0 <= answer < len(choices):
        return FolderSuggestion(folder, choices[answer].outcome, 100, [Reason(True, "Your answer")], files=n)
    if name.lower().startswith(HOLDING_PREFIXES) or HOLDING_WORDS & set(name_words):
        why = "A restored copy of another drive" if "restored" in name_words \
            else f"Looks like a holding folder (“{name}”)"
        return result(FOLDER_REVIEW, 60, Reason(False, why), Reason(False, "Only you know whether it should stay"))
    program = is_program(p, folder)
    if program:
        p.units.add(folder)
        return result(keep, 95, Reason(True, program), Reason(True, "A program is kept whole"))
    messy = sorted(MESSY_WORDS & set(name_words))
    if messy:
        return result(SORT_INSIDE, 90, Reason(True, f"Generic name “{name}”"))
    archive = _zip_beside(p, folder)
    if archive:
        return result(keep, 95, Reason(True, f"Unzipped copy of “{archive}” beside it"))
    sample = files[:SAMPLE]
    share, word = _name_share(p, name_words, sample)
    if share >= NAME_SHARE:
        k = round(share * len(sample))
        return result(keep, 60 + 40 * share, Reason(True, f"{k} of {len(sample)} files mention “{word}”, "
                                                          f"like the folder name"))
    return None


def _decide_spread(p, folder: str, source) -> FolderSuggestion:
    """Where the folder's files would go if it weren't there."""
    from .planner import SORT_OUT

    files = p.files_under[folder]
    n = len(files)
    sample = files[:SAMPLE]

    def result(outcome, percent, *reasons):
        return _result(folder, n, outcome, percent, *reasons)

    homes = Counter()
    for i in sample:
        s = p._suggest(i, outside=folder)
        if s.destination and s.percent >= CLEAR_HOME:
            homes[s.destination] += 1
    spread = sum(homes.values()) / len(sample) if sample else 0.0
    examples = ", ".join(p.label(f) for f, _ in homes.most_common(3))
    if len(homes) >= 2 and spread >= MESSY_SHARE and (source.mode == SORT_OUT or n >= MIN_FILES):
        return result(SORT_INSIDE, 50 + 45 * spread,
                      Reason(True, f"{sum(homes.values())} of {len(sample)} files clearly belong in "
                                   f"{len(homes)} different folders ({examples})"))
    if source.mode != SORT_OUT:
        return result(STAYS, 70 + 25 * (1 - spread), Reason(True, "An organised folder: its files have no clearer "
                                                                  "home elsewhere"))
    knit = _close_knit(p, folder, sample)
    if n >= 3 and knit >= CLOSE_KNIT:
        return result(KEEP_TOGETHER, 50 + 45 * knit,
                      Reason(True, f"{round(knit * len(sample))} of {len(sample)} files are most like each other"))
    if len(homes) == 1 and spread >= MESSY_SHARE:
        return result(KEEP_TOGETHER, 50 + 40 * spread, Reason(True, f"All its files fit {examples}"))
    return result(FOLDER_REVIEW, 50, Reason(False, "Not clear whether these files belong together"))


def _zip_beside(p, folder: str) -> str:
    parent, name = os.path.dirname(folder), os.path.basename(folder).lower()
    for i in p.direct.get(parent, []):
        record = p.records[i]
        if record.kind == "archive" and os.path.splitext(record.name)[0].lower() == name:
            return record.name
    return ""


def _distinctive(p, name_words: list[str]) -> list[str]:
    return [w for w in name_words if len(w) >= 3 and w not in DEFAULT_NAME_WORDS and w not in MESSY_WORDS
            and p.idf.get(f"w:{w}", 0) > 2.5]


def _name_share(p, name_words: list[str], files: list[int]) -> tuple[float, str]:
    best = (0.0, "")
    for w in _distinctive(p, name_words):
        hits = sum(1 for i in files if w in p.clues[i].name_words or w in p.clues[i].content_words)
        share = hits / len(files) if files else 0.0
        best = max(best, (share, w))
    return best


def _close_knit(p, folder: str, files: list[int]) -> float:
    if not hasattr(p, "everything"):
        from .planner import _Index

        p.everything = _Index([c.vector for c in p.clues])
    inside = 0
    for i in files:
        found = p.everything.search(p.clues[i].vector, exclude=i)
        if found and _inside(p.records[found[0][0]].path, folder):
            inside += 1
    return inside / len(files) if files else 0.0


# ---------------------------------------------------------------- kept-together folders
def place_kept_folders(p, plan: Plan) -> None:
    weak = []
    for f in plan.folders:
        if f.outcome != KEEP_TOGETHER or f.destination:
            continue
        votes = Counter()
        sample = p.files_under[f.path][:SAMPLE]
        suggestions = [p._suggest(i) for i in sample]
        for s in suggestions:
            if s.destination and s.percent >= 50 and not _inside(s.destination, f.path):
                votes[s.destination] += s.percent
        if not votes or votes.most_common(1)[0][1] < 50 * len(sample) / 2:
            weak.append(f)
        if not votes:
            continue
        best, score = votes.most_common(1)[0]
        f.destination = _climb(p, best)
        if f.percent < 100:
            f.percent = min(f.percent, round(100 * score / (100 * len(sample))))
        fitting = sum(1 for s in suggestions if s.destination == best)
        f.reasons.append(Reason(True, f"{fitting} of {len(sample)} files fit {p.label(best)}"))
        if f.destination != best:
            f.reasons.append(Reason(True, f"{p.label(f.destination)} holds folders like it, such as "
                                          f"“{os.path.basename(_unit_under(f.destination, best))}”"))
    strong = [f for f in plan.folders if f.outcome == KEEP_TOGETHER and f.destination and f not in weak]
    for f in weak:
        mine = set(_distinctive(p, words(os.path.basename(f.path))))
        twin = next((o for o in strong if mine & set(_distinctive(p, words(os.path.basename(o.path))))), None)
        if twin:
            f.destination, f.percent = twin.destination, min(twin.percent, f.percent)
            f.reasons = [r for r in f.reasons if " files fit " not in r.text and "holds folders" not in r.text]
            f.reasons.append(Reason(True, f"Related to “{os.path.basename(twin.path)}”, which goes to "
                                          f"{p.label(twin.destination)}"))
        elif not f.destination:
            f.outcome = FOLDER_REVIEW
            f.reasons.append(Reason(False, "No folder fits it as a whole"))


def _unit_under(home: str, best: str) -> str:
    rel = os.path.relpath(best, home).split(os.sep)[0]
    return os.path.join(home, rel)


def _climb(p, best: str) -> str:
    """A file's best folder may sit inside a project folder; a kept-together folder goes beside that project."""
    root = p._root_of(best)
    home, folder = best, best
    while path_key(folder) != path_key(root) and _inside(folder, root):
        if _is_unit(p, folder):
            home = os.path.dirname(folder)
        folder = os.path.dirname(folder)
    return home


def _is_unit(p, folder: str) -> bool:
    """A folder named after something only its own files mention (e.g. "Project Osprey")."""
    under = [i for f, items in p.by_folder.items() if _inside(f, folder) for i in items]
    if not under:
        return False
    for w in _distinctive(p, words(os.path.basename(folder))):
        mention = [i for i, c in enumerate(p.clues) if w in c.name_words or w in c.content_words]
        inside = [i for i in mention if _inside(p.records[i].path, folder)]
        covered = sum(1 for i in under if w in p.clues[i].name_words or w in p.clues[i].content_words)
        if mention and len(inside) >= 0.8 * len(mention) and covered >= 0.5 * len(under):
            return True
    return False


# ---------------------------------------------------------------- topics
def _topic_words(name: str) -> set[str]:
    return {w for w in words(name) if len(w) >= 4 and w not in DEFAULT_NAME_WORDS and w not in MESSY_WORDS
            and w not in COPY_WORDS and w not in GENERIC_TOPIC_WORDS}


def find_topics(p, plan: Plan) -> None:
    folder_plan = {path_key(f.path): f for f in plan.folders}
    for source in p.sources:
        items = {}          # path -> (is_folder, current parent, planned place)
        for s in plan.files:
            if _inside(s.path, source.root):
                items[s.path] = (False, s.current_folder, s.destination or s.current_folder)
        for folder in p.files_under:
            if not _inside(folder, source.root) or any(_inside(folder, h) and path_key(folder) != path_key(h)
                                                       for h in p.held) \
                    or any(_inside(folder, u) for u in p.units):
                continue
            decided = folder_plan.get(path_key(folder))
            if decided and decided.outcome in (SORT_INSIDE, FOLDER_REVIEW):
                continue
            parent = os.path.dirname(folder)
            planned = decided.destination if decided and decided.destination else parent
            items[folder] = (True, parent, planned)
        by_word: dict[str, set[str]] = defaultdict(set)
        for path in [i for i in items if not p.is_left_out(i)]:
            for w in _topic_words(os.path.basename(path)):
                by_word[w].add(path)
        groups: list[tuple[list[str], set[str]]] = []
        for w, members in sorted(by_word.items(), key=lambda kv: -len(kv[1])):
            if len(members) < 3 or len(members) > TOPIC_NAME_SHARE * len(items) \
                    or not any(items[m][0] for m in members):
                continue
            if len({path_key(items[m][1]) for m in members}) < 2:
                continue
            for group_words, group in groups:
                if len(group & members) >= 0.7 * len(group | members):
                    group_words.append(w)
                    group |= members
                    break
            else:
                groups.append(([w], set(members)))
        for group_words, members in groups:
            folders = [m for m in members if items[m][0]]
            members = {m for m in members if not any(f != m and _inside(m, f) for f in folders)}
            if len(members) < 3 or len({path_key(items[m][1]) for m in members}) < 2:
                continue
            ends = set()
            for m in members:
                is_folder, _, planned = items[m]
                if not is_folder:
                    holder = next((f for f in folders if _inside(planned, f)), None)
                    planned = items[holder][2] if holder else planned
                ends.add(path_key(planned))
            if len(ends) < 2:
                continue
            _add_topic(p, plan, source, group_words, sorted(members), items, folder_plan)


def _topic_name(group_words: list[str], members: list[str]) -> str:
    for m in members:
        found = words(os.path.basename(m))
        if all(w in found for w in group_words):
            return " ".join(w.capitalize() for w in sorted(group_words, key=found.index))
    return " ".join(w.capitalize() for w in group_words)


def _add_topic(p, plan, source, group_words, members, items, folder_plan) -> None:
    name = _topic_name(group_words, members)
    places = Counter(path_key(items[m][1]) for m in members)
    place_path = {path_key(items[m][1]): items[m][1] for m in members}
    pool = set(p.by_folder) | {m for m in members if items[m][0]}
    matching = [f for f in pool if all(w in words(os.path.basename(f)) for w in group_words)]
    copies = Counter(path_key(os.path.dirname(f)) for f in matching)
    matching = [f for f in matching if copies[path_key(os.path.dirname(f))] < 2
                and not re.search(r"\(\d+\)|\d+\.\d+", os.path.basename(f))]
    new_folder = False
    busiest = place_path[places.most_common(1)[0][0]]
    if matching:
        home = sorted(matching, key=lambda f: (-sum(1 for m in members if _inside(m, f)), len(f)))[0]
    elif path_key(busiest) != path_key(source.root):
        home = busiest
    else:
        home, new_folder = os.path.join(source.root, name), True
    topic = Topic(name, members, home, new_folder)
    plan.topics.append(topic)
    p.topic_by_key = getattr(p, "topic_by_key", {})
    p.topic_by_key[topic_key(source.root, name)] = topic

    where = ", ".join(f"{p.label(place_path[k])} ({n})" for k, n in places.most_common())
    choices = [Choice(f"Together in {p.label(home)}" + (" (new folder)" if new_folder else ""), home)]
    if path_key(busiest) != path_key(home) and path_key(busiest) != path_key(source.root):
        choices.append(Choice(f"Together in {p.label(busiest)}", busiest))
    projects = next((f for f in sorted(p.by_folder) if os.path.basename(f).lower() == "projects"
                     and _inside(f, source.root)), None)
    person = os.path.basename(busiest)
    if projects and re.fullmatch(r"[A-Z][a-z]+ [A-Z][a-z]+", person):
        choices.append(Choice(f"A project for {person}: {p.label(projects)}/{person}/{name} (new folders)",
                              os.path.join(projects, person, name)))
    choices.append(Choice("Leave them where they are", None))
    plan.questions.append(Question(topic_key(source.root, name),
                                   f"“{name}” files and folders are in {len(places)} places: {where}. "
                                   f"Where should they live?", choices, members))

    reason = Reason(False, f"Part of “{name}”, found in {len(places)} places: see the question")
    member_set = {path_key(m) for m in members}
    for s in plan.files:
        if path_key(s.path) in member_set:
            s.destination, s.new_folder, s.topic = home, new_folder, name
            s.percent = min(s.percent, TOPIC_WAIT_PERCENT) if s.destination != s.current_folder else s.percent
            s.reasons = [Reason(True, f"Together with the other “{name}” files"), reason]
    folder_members = [m for m in members if items[m][0]]
    moving = [m for m in folder_members if path_key(m) != path_key(home)]
    plan.files[:] = [s for s in plan.files if not any(_inside(s.path, f) for f in moving)]
    for m in folder_members:
        decided = folder_plan.get(path_key(m))
        staying = path_key(m) == path_key(home)
        if decided is None:
            decided = FolderSuggestion(m, STAYS, 0, files=len(p.files_under[m]))
            plan.folders.append(decided)
            folder_plan[path_key(m)] = decided
        decided.topic = name
        decided.outcome = STAYS if staying else KEEP_TOGETHER
        decided.destination = None if staying else home
        decided.percent = TOPIC_WAIT_PERCENT
        decided.reasons = [Reason(True, f"Together with the other “{name}” files"), reason]


# ---------------------------------------------------------------- questions and answers
def ask_about_folders(p, plan: Plan) -> None:
    for f in sorted((f for f in plan.folders if f.outcome == FOLDER_REVIEW), key=lambda f: -f.files):
        if len(plan.questions) >= MAX_QUESTIONS:
            break
        source = p._source_of(f.path)
        plan.questions.append(Question(
            folder_key(f.path),
            f"What should happen to “{os.path.basename(f.path)}” ({f.files} files) in "
            f"{p.label(os.path.dirname(f.path))}?",
            _folder_choices(source.mode), [f.path]))


def apply_answers(p, plan: Plan) -> None:
    plan.questions.sort(key=lambda q: (not q.key.startswith("topic:"), -len(q.about)))
    del plan.questions[MAX_QUESTIONS:]
    for q in plan.questions:
        answer = p.answers.get(q.key)
        if answer is None or not 0 <= answer < len(q.choices) or not q.key.startswith("topic:"):
            continue
        q.answer = answer
        chosen = q.choices[answer].destination
        about = {path_key(m) for m in q.about}
        for s in plan.files:
            if path_key(s.path) in about:
                s.destination = chosen or s.current_folder
                s.new_folder = bool(chosen and not os.path.isdir(chosen))
                s.percent, s.reasons = 100, [Reason(True, "Your answer")]
        for f in plan.folders:
            if path_key(f.path) in about:
                staying = chosen is None or path_key(chosen) == path_key(f.path)
                f.outcome = STAYS if staying else KEEP_TOGETHER
                f.destination = None if staying else chosen
                f.percent, f.reasons = 100, [Reason(True, "Your answer")]
        topic = getattr(p, "topic_by_key", {}).get(q.key)
        if topic and chosen:
            topic.home, topic.new_folder = chosen, not os.path.isdir(chosen)
