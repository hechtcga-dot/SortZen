# SortZen Roadmap

Each phase ends with its tests passing. Engine behaviour and UI never change in the same
step.

## Alpha (versions 0.x, test folders only)

| # | Phase | Status |
|---|-------|--------|
| 0 | Repository set-up: package layout, workspace window, AI provider interface, job runner, settings, tests | **Done** |
| 1 | Synthetic test folders; scanner and file readers with remembered results | **Done** |
| 2 | Sorting engine: overview (topics, homes, new folders, misplaced files), questions, rules, learning from sorted folders, sureness percentage and how it was worked out; subfolders (stays, keep together, sort the inside, Review); sort into other folders or tidy in place | To do |
| 3 | AI step: service drop-down, key storage, privacy settings, two passes, batches, cost estimate and cap | To do |
| 4 | Mover: move plan, whole-folder moves, removing emptied folders, name clashes, cross-drive copy and check, run log, Undo | To do |
| 5 | Screens: first setup (folders, privacy, AI, autonomy level), scan, questions, plan with Ready and Review, percentage breakdowns, apply, Undo, corrections, rule suggestions | To do |
| 6 | Alpha build: program folder and per-user installer from the Windows build workflow | To do |
| 7 | Alpha test (below) | To do |

## After the alpha
1. Renaming screen (SPEC §12).
2. In-app updater (SPEC §13).
3. Reading scanned PDFs (OCR), finding duplicates, sorting on a schedule.

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

## Alpha test: pass criteria
- No file is lost or overwritten; Undo restores every file.
- After first-run learning, local sorting (no AI) places most test files correctly; the
  score is recorded so later changes can't quietly lower it.
- With AI on, 1,000 files cost no more than $0.25, and the estimate shown before the run
  is close to the actual cost.
- The three privacy levels (name only, random words, beginning of file) are compared for
  accuracy and cost, to choose the default.
- Percentages are honest: of the files marked 90% sure, about 9 in 10 are right, and the
  same holds at other levels.
- Every subfolder in the test folders gets the expected outcome, and a kept-together
  folder arrives with its structure unchanged.
- Every topic in the answer key ends up in one folder, or SortZen asks a question about
  it; misplaced files inside organised folders are found.
- A correction changes the next suggestion for similar files.
- A repeat scan of 1,000 unchanged files takes a few seconds.
