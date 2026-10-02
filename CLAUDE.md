# CLAUDE.md — SortZen

## What this is
SortZen is a Windows desktop program that sorts messy folders, such as Downloads, into the
right destination folders, learns how its users sort, and suggests better file names.
Local first; AI (Gemini by default) only for files it can't place, within $0.25 per 1,000
files.

## Read first
1. `docs/SPEC.md`: what SortZen does; every product decision.
2. `docs/ROADMAP.md`: phases, the alpha test and what is done.

## Layout
```
src/sortzen/
  config.py            constants, per-user storage paths (SORTZEN_DATA_DIR override)
  ai/                  provider interface, Gemini and web adapters, service list, JSON parsing,
                       privacy.py (scrubbing, name-only rules, previews), costs.py (prices),
                       sorter.py (two passes in batches, spending cap)
  tasks/               typed job events, background job runner (cancel token = Stop Safely)
  scanning/            file kinds, readers (Word, PDF, Excel, PowerPoint, text, photos, zip,
                       programs), fingerprints, scanner (skip rules, remembered results)
  engine/              sorting engine (never touches files): features.py (clues from names,
                       contents, kinds), planner.py (folder profiles, suggestions, percentages,
                       reasons, corrections), overview.py (subfolders, kept-together folders,
                       topics, questions, answers), duplicates.py (exact copies, the copy
                       kept and why), ai_evidence.py (AI answers as evidence), plan.py (Suggestion, FolderSuggestion, Topic, Question,
                       Plan)
  mover/               moves confirmed files and folders (never decides): no overwriting,
                       copy and check across drives, step-by-step run log, Undo
  repositories/        settings.json, API keys (Windows Credential Manager via keyring),
                       file_index.py (SQLite: remembered scan results), ai_answers.py
                       (SQLite: remembered AI answers)
  services/            AppService: the only API the window uses (folders, autonomy, answers,
                       corrections, make_plan, move, undo, AI step, profiles,
                       diagnostics); profile.py (.szprofile files); plan_view.py (Ready/Review/
                       Staying rows, problems, display paths, Excel export); moving.py
                       (ticked rows to move requests, the confirmation preview)
  ui/                  PySide6 window (main_window.py), folders_page.py, plan_page.py,
                       questions_page.py, progress_window.py (+ tips.py), dialogs.py,
                       move_dialogs.py (confirm, result, undo a move), copies_page.py,
                       ai_widgets.py (AI service and privacy panels), ai_dialog.py,
                       settings_window.py,
                       sortable.py (click-to-sort columns), theme, fonts (OFL), icon
packaging/             launcher.py (entry point), sortzen.spec (PyInstaller program folder),
                       sortzen.iss (per-user Inno Setup installer), make_icon.py, README.txt
                       (shipped with each build), BUILD_WINDOWS.bat (local build)
tests/                 unittest suites (window tests run offscreen)
  fixtures/            make_test_folders.py: made-up Downloads and My Drive (about 440 files
                       and 37 subfolders to sort, topics), sorted folders, answer key;
                       shared_test_folders() builds them once per test run
.github/workflows/     tests.yml: tests and self-test on Windows on every push;
                       windows-build.yml: tests, program, installer, install test, release
```

## Commands
```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m unittest discover -s tests -t .           # run tests (must stay green)
python packaging/launcher.py                        # run the program
python tests/fixtures/make_test_folders.py OUT      # build the test folders in OUT
python -m tests.engine_score                        # grade the engine against the answer key
python packaging/launcher.py --self-test=out.json   # start, check bundled pieces, exit
python packaging/launcher.py --remove-data          # forget keys, delete settings (uninstaller)
```
`tests/test_wording.py` enforces the writing rules below.

## Writing rules (code, comments, docs, commit messages)
- Describe what the program does, e.g. "SortZen moves files after confirmation", not who
  asked for it or why it was decided.
- Never name who requested a feature or made a decision. When people must be
  mentioned, say "users".
- Never reference other projects, repositories or apps. Everything needed lives in this
  repository; copy instructions in rather than linking out.
- No decision logs, request notes or history in docs or comments. The SPEC states current
  behaviour only; history lives in git.
- Examples and test data use made-up names only.

## Tech stack
Python 3.12+, Windows 10/11; PySide6; AI provider interface (Gemini, Claude, ChatGPT,
OpenRouter, Ollama); SQLite for remembered results and learning; keyring (Windows
Credential Manager) for API keys; Pillow (photo details), pypdf (PDF text); PyInstaller and
Inno Setup; unittest.

## Architecture rules
- UI → services only. Services return data or typed errors; no dialogs in business logic.
- The sorting engine decides and never touches files; the mover moves and never decides.
- Engine behaviour and UI never change in the same step; the engine is pinned by tests on
  the synthetic test folders first.
- Nothing is moved, renamed or deleted without a confirmed preview, and every run can be
  undone.
- Only folders users added are read. API keys and real user files are never committed.
- The interface follows SPEC §4.

## Builds and releases
- Builds are made only when asked. Changes are committed and pushed; the version bump,
  README and the Windows build wait until a build is asked for.
- A build is published by pushing a tag `vX.Y.Z` (or running "Windows build" by hand with
  `release_tag`); the workflow puts `SortZen-Setup-X.Y.Z.exe` and README.txt on the
  repository's Releases page as a pre-release.
- Each build is developed on its own branch (`release/0.1`, …) and merged into `main`
  when the next one starts.
- Before a build: bump the version (below), and update `packaging/README.txt` ("SortZen
  X.Y - README", the setup file name, "What's new in X.Y") and the installer default in
  `packaging/sortzen.iss`; `tests/test_version.py` checks they agree.

## Versions
- One version number: `__version__` in `src/sortzen/__init__.py`. The window, the program
  and the installer read it; a test checks they agree.
- Alpha builds are 0.1, 0.2 …; each new build goes up one step.
- A few small fixes or tweaks to a released build can go out as a third number (0.2.3).
- As soon as something major is asked for, or the small tweaks pile up, everything not yet
  built (the small fixes included) goes into the next step (0.3) instead. The work is never
  split into a small build plus a separate major one.

## Working style
- Explain changes in plain language; prefer small, verifiable steps.
- Ask when a product decision is unclear rather than guessing.
