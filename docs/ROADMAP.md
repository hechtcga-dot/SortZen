# SortZen Roadmap

Each phase ends with its tests passing. Engine behaviour and UI never change in the same
step. Status: planning, nothing built.

## Alpha (versions 0.x, test folders only)

| # | Phase | Status |
|---|-------|--------|
| 0 | Repository set-up: package layout, workspace window, AI provider interface, job runner, settings, tests | To do |
| 1 | Synthetic test folders; scanner and file readers with remembered results | To do |
| 2 | Sorting engine: rules, learning from sorted folders, confidence and reason | To do |
| 3 | AI step: service drop-down, key storage, privacy settings, two passes, batches, cost estimate and cap | To do |
| 4 | Mover: move plan, name clashes, cross-drive copy and check, run log, Undo | To do |
| 5 | Screens: first setup (folders, privacy, AI), scan, review with Needs you, apply, Undo, corrections, rule suggestions | To do |
| 6 | Alpha build: program folder and per-user installer from the Windows build workflow | To do |
| 7 | Alpha test (below) | To do |

## After the alpha
1. Renaming screen (SPEC §12).
2. In-app updater (SPEC §13).
3. Reading scanned PDFs (OCR), finding duplicates, sorting on a schedule.

## Phase 1: test folders
A generator script builds a test setup from made-up content only:
- a "Downloads" folder of about 300 mixed files: installers, zip files, photos with camera
  details, screenshots, music, videos, and Word, PDF and Excel files for an invented
  employer ("Example Co.") alongside personal files (a resume mentioning Example Co.,
  recipes, receipts);
- already-sorted destination folders (Documents/Word/Work, Documents/Word/Personal,
  Pictures/…) for first-run learning;
- the expected destination of every file (the answer key).

Engine tests compare SortZen's choices with the answer key and report a score.

## Alpha test: pass criteria
- No file is lost or overwritten; Undo restores every file.
- After first-run learning, local sorting (no AI) places most test files correctly; the
  score is recorded so later changes can't quietly lower it.
- With AI on, 1,000 files cost no more than $0.25, and the estimate shown before the run
  is close to the actual cost.
- The three privacy levels (name only, random words, beginning of file) are compared for
  accuracy and cost, to choose the default.
- A correction changes the next suggestion for similar files.
- A repeat scan of 1,000 unchanged files takes a few seconds.
