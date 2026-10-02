# SortZen Roadmap

Each phase ends with its tests passing. Engine behaviour and UI never change in the same
step.

## Alpha (versions 0.x)

Alpha 0.1 is **plan only**: it scans, asks its questions and shows the full plan with
every percentage and its reasons, but moves nothing, so it can run safely on real folders.
Files move from alpha 0.2.

| # | Phase | Status |
|---|-------|--------|
| 0 | Repository set-up: package layout, workspace window, AI provider interface, job runner, settings, tests | **Done** |
| 1 | Synthetic test folders; scanner and file readers with remembered results | **Done** |
| 2a | Sorting engine, file by file: folder profiles, suggestions with a percentage and how it was worked out, runner-up, misplaced files in organised folders | **Done** |
| 2b | Sorting engine, the overview: subfolder outcomes (stays, keep together, sort the inside, Review), topics and their homes, one-level new folders, questions | To do |
| 3 | Plan screen (read-only): add folders (sort into other folders or tidy this folder), scan, questions, plan with Ready and Review, percentage breakdowns, corrections, export the plan to Excel | To do |
| 4 | **Alpha 0.1 build**: program folder and per-user installer from the Windows build workflow; plan only | To do |
| 5 | AI step: service drop-down, key storage, privacy settings (name only, beginning of file), two passes, batches, cost estimate and cap | To do |
| 6 | Mover: whole-folder moves, new folders, removing emptied folders, name clashes, cross-drive copy and check, Google link files kept in their drive, run log, Undo | To do |
| 7 | **Alpha 0.2 build**: files move | To do |

## After the alpha
1. Removing duplicates (copies are grouped and flagged in the alpha).
2. Renaming screen (SPEC §12).
3. In-app updater (SPEC §13).
4. Rule suggestions, the random-word privacy option, deeper new-folder structures.
5. Reading scanned PDFs (OCR), sorting on a schedule.

## Phase 1: test folders
`tests/fixtures/make_test_folders.py` builds a test setup from made-up content only, with
the mess real folders have: copies ("name (1).xlsx"), typos and odd capitals, random-code
and scanner-generated names, scanned PDFs with no text, Google link files, shortcuts, an
applicant's resume beside the user's own, and work and personal files mixed together.
- **Downloads**: loose files, a messy "older downloads" folder with a project folder
  inside it, a project folder with its own subfolders, and an unzipped folder next to its
  .zip. Destinations are in **Sorted** (Documents/Work/…, Documents/Personal/…, Pictures,
  Music, Videos, Software, Archives), which already hold examples.
- **My Drive**: a cloud drive tidied in place: loose files among organised folders that
  stay where they are, messy folders whose files belong in the organised ones, and folders
  only users can decide about (a holding folder, a former colleague's restored drive).
- **My Drive/Owen Sample**: a person's folder holding their own papers (which stay) and
  a program built for them: a version series of zips, extracted copies of the program,
  and drive downloads, alongside loose files about the same program elsewhere.
- **answer_key.json**: the expected destination of every file (its own folder when it
  should stay, or Review), the expected outcome of every subfolder, and the topics whose
  members must end up together.

Engine tests compare SortZen's choices with the answer key and report a score.

## Engine score (phases 2a and 2b)
`tests/test_engine.py` runs the engine on the test folders and checks it against the
answer key: how many files get the right top suggestion, whether percentages are honest
(of the files marked 90% sure, about 9 in 10 are right), whether Review-only files stay
below the autonomy level, subfolder outcomes, topics, and misplaced files. The score is
recorded so later changes can't quietly lower it. `python -m tests.engine_score` prints
the score and the mistakes.

| Measure (2a, file by file) | Score | Test requires |
|---|---|---|
| Top suggestion right | 97.2% | 93% |
| Ready (90%+) suggestions right | 100% (312 files) | 97% |
| Files placed without asking | 80% | 70% |
| Review-only files kept for Review | 100% | 95% |
| Wrong moves out of organised folders | 0 | at most 2 |
| Misplaced files found | 2 of 3 (the third shows as staying, with the alternative as a reason) | all but one |

## Alpha 0.1 test: pass criteria (plan only, real folders)
- Nothing on disk changes.
- On a real folder, most Ready suggestions are right, and Review holds what is truly
  unclear; corrections change the next suggestion for similar files.
- Questions are few and worth asking.
- A scan and plan of a few thousand files finishes in minutes; a repeat scan of 1,000
  unchanged files takes a few seconds.

## Alpha 0.2 test: pass criteria
- No file is lost or overwritten; Undo restores every file.
- A kept-together folder arrives with its structure unchanged; emptied folders are removed
  and Undo recreates them.
- With AI on, 1,000 files cost no more than $0.25, and the estimate shown before the run
  is close to the actual cost.
- Name only and beginning of file are compared for accuracy and cost, to choose the
  default.
