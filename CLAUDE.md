# CLAUDE.md — SortZen

## What this is
SortZen is a Windows desktop program that sorts messy folders, such as Downloads, into the
right destination folders, learns how its users sort, and suggests better file names.
Local first; AI (Gemini by default) only for files it can't place, within $0.25 per 1,000
files.

## Read first
1. `docs/SPEC.md`: what SortZen does; every product decision.
2. `docs/ROADMAP.md`: phases, the alpha test and what is done.

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
Credential Manager) for API keys; PyInstaller and Inno Setup; unittest.

## Architecture rules
- UI → services only. Services return data or typed errors; no dialogs in business logic.
- The sorting engine decides and never touches files; the mover moves and never decides.
- Engine behaviour and UI never change in the same step; the engine is pinned by tests on
  the synthetic test folders first.
- Nothing is moved, renamed or deleted without a confirmed preview, and every run can be
  undone.
- Only folders users added are read. API keys and real user files are never committed.
- The interface follows SPEC §4.

## Versions
- One version number: `__version__` in `src/sortzen/__init__.py`. The window, the program
  and the installer read it; a test checks they agree.
- Alpha builds are 0.1, 0.2 …; each new build goes up one step. Fixes to a released build
  add a third number (0.2.1).

## Working style
- Explain changes in plain language; prefer small, verifiable steps.
- Ask when a product decision is unclear rather than guessing.
