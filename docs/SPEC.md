# SortZen — Product Specification

What SortZen does and how it behaves. This file is the reference for every product
decision; when the code and this file disagree, this file wins until it is changed.

## 1. Product
- SortZen is a Windows desktop program that sorts messy folders, such as Downloads, into
  the right destination folders, learns how its users sort, and suggests better file names.
- Local first: everything that can be done on the PC is done on the PC. AI is optional and
  is only asked about files SortZen can't place by itself.
- Users: SortZen is intended for individual use and is not currently intended for sale.

## 2. Components
- Workspace window (PySide6): folder tree, tabs, right-click menus, drag and drop from
  Explorer, progress window, Undo.
- AI provider interface with adapters for Gemini, Claude, ChatGPT, OpenRouter and Ollama.
- Background job runner with typed progress events and Stop Safely.
- Per-user storage in `%LOCALAPPDATA%\SortZen` (override with `SORTZEN_DATA_DIR`).
- Packaging: PyInstaller program folder (no one-file exe, no UPX compression), Inno Setup
  per-user installer, GitHub Actions Windows build.

## 3. Architecture rules
- UI → services only. The UI never reads files, moves files or calls the AI directly.
- The **sorting engine** decides where a file goes and never touches files on disk. The
  **mover** moves files and never decides.
- Engine behaviour and UI never change in the same step. Engine behaviour is pinned by
  tests on the synthetic test folders before it changes.
- Nothing is moved, renamed or deleted until users confirm a preview.

## 4. Interface principles
- No silent waits: slow work runs in the background and results are remembered; otherwise
  a progress window shows what is happening.
- Everything is right-clickable, with the same actions as the buttons; Shift-click and
  Ctrl-click select several items.
- Every change can be undone (Ctrl+Z and Undo buttons). Optional panels can be shown or
  hidden.
- Features are reachable from the toolbar, the menus, the folder tree and the welcome
  window.
- Text is selectable; no wasted space; nothing is cut off or overlapping.
- Wording is plain and says what will happen; new features carry a short hint underneath.
- Tick boxes and toggles respond instantly and save in the background.
- Examples and test data use made-up names only.

## 5. Folder access
- SortZen only reads and moves inside folders users add:
  - **Source folders**: the messy folders to sort. Each is added in one of two ways:
    - **Sort into other folders** (e.g. Downloads): its files and subfolders go to the
      destination folders.
    - **Tidy this folder** (e.g. a cloud drive): it is its own destination. Its organised
      subfolders stay where they are and receive files; loose files and messy subfolders
      are sorted into them (and into any other destination folders).
  - **Destination folders**: where files may go (e.g. Documents, Pictures, Videos, Music,
    or any other folder), including all their subfolders.
- First run offers the standard Windows folders as a starting template, located through
  Windows so that folders moved to OneDrive are found correctly.
- Folders can be added or removed at any time. Nothing outside them is read.
- **Subfolders inside a source folder** each get one of these outcomes, with a percentage
  and reasons like files (§7):
  - **Stays** (tidy this folder only): an organised folder that stays where it is. Files
    inside it that clearly belong elsewhere are still suggested to move out.
  - **Keep together**: the folder moves as one item with everything inside, structure
    unchanged, to a destination chosen like a file's (e.g. a folder of "Project 1" files
    that mention Example Co. → Documents/Work/Project 1).
  - **Sort the inside**: the folder is treated as another messy folder and each file in it
    is sorted on its own. Its own subfolders get the same check, so a project folder inside
    a messy folder still stays together. Once emptied, the folder is deleted (Undo
    restores it).
  - **Review**: the signs are mixed, so users decide.
- Signs a folder belongs together: many files share words with the folder name or with
  each other (in names or contents); its own orderly subfolders; program or project files;
  a matching .zip next to it (an unzipped download); one topic or a short span of dates.
- Signs a folder is messy: a generic name ("older downloads", "New folder", "misc",
  "stuff", "temp"); many unrelated file types and topics; dates spread over months or
  years.
- Messy folders are found in rounds: folders that are clearly messy by name come first,
  then a folder counts as messy when most of its files clearly belong in several different
  organised folders elsewhere, comparing only with folders not already found messy.
- A kept-together folder goes where most of its files fit. When the best fit is inside a
  project folder (e.g. Projects/Project Osprey), it goes beside that project instead. When
  its own files give no clear answer, it follows a related kept-together folder with the
  same distinctive name.
- The AI is only asked about a folder when these signs are unclear, and then sees the
  folder name and about 20 file names.
- On the review screen any folder can be switched between keep together and sort the
  inside; the choice is learned like a file correction.
- A destination folder inside another destination is scanned once, as part of the outer
  one; a source folder inside a destination is never treated as a destination.
- Always skipped, and counted in the scan summary: hidden and system files, Windows
  housekeeping files (desktop.ini, Thumbs.db), Office lock files (~$…), downloads still in
  progress (.crdownload, .part …), files in use, the Recycle Bin, and Windows and program
  folders. Shortcuts are sorted as files and never followed into other folders.
- **OneDrive cloud-only files** are sorted by name and details only, because reading their
  contents would download them. A setting turns this off.
- **Google Drive for desktop** (the drive labelled "Google Drive"): reading a file there can
  make Google Drive download it, so its files are sorted by name and details only unless
  "Read file contents on Google Drive" is on (Settings).
- **Google Drive link files** (.gdoc, .gsheet, .gslides, .gform) are small pointers to
  documents that stay online. They are sorted by name and type, and only move to folders
  inside the same Google Drive, because moving one out of the drive disconnects it.

## 6. Reading files (on the PC, no AI)
- Details: name, type, size, dates, current folder.
- Contents: Word (.docx: text, title, author), PDF (typed text from the first 2 pages,
  title, author), Excel (.xlsx), PowerPoint (.pptx), text and CSV (any common encoding),
  photo details (camera, date taken, size), the names of files inside .zip archives, and
  program details (.exe: product and company, read through Windows). Google link files
  count as documents, spreadsheets, presentations or forms; the account they belong to is
  not recorded.
- PDFs with no typed text are marked as scans (reading them needs OCR, after the alpha).
- Text is kept up to 20,000 characters per file. Files over 50 MB (other than photos,
  archives and programs) are sorted by name and details only.
- A damaged file is still listed and sorted by name and details, with the reason shown.
- Results are remembered per file (path, size, date changed), so a repeat scan of an
  unchanged folder takes seconds. Stop Safely keeps everything scanned so far.
- **Be gentle with my computer** (Settings): reading runs at the lowest processor and disk
  priority with short rests between files, so the computer stays quiet and responsive;
  it takes longer.
- Planning compares each file first with the files that share its distinctive clues (rare
  words and details), and works out full similarity for at most 200 of them, so planning
  time grows in step with the number of files (about 5 seconds for 9,000 files).
- Each file gets a content fingerprint: small files are hashed whole; large files from
  their size plus samples at the start, middle and end, so big videos are as quick as
  small files. Learning is tied to the fingerprint, not the name, so a file keeps its
  history when it is moved or renamed.

## 7. How SortZen decides
SortZen looks at everything first, then decides file by file.

### 1. Overview
Before suggesting any move, SortZen scans every added folder at every level and builds an
overview of what is there:
- **Topics**: groups of related files and folders wherever they are, found from shared
  distinctive words in names (words in at most 15% of names, and at least one folder among
  them) and contents, people's names, version series
  (`Name_1.0.zip` … `Name_1.6.zip`), copies (`name (1)`, `folder (4)`), and what is
  stored together. For example: "Garden Planner" files in My Drive, in My Drive/Owen
  Sample and in Documents/Projects are one topic, a program built for Owen Sample.
- **A home for each topic**: the existing folder where most of it already lives or whose
  name matches, or a **new folder** when nothing fits, nested where it belongs (e.g.
  Projects/Programming/Owen Sample/Garden Planner). New folders are part of the plan:
  created only when the plan is confirmed, and removed by Undo.
- **Misplaced files**: files inside organised folders that clearly belong to another
  topic are suggested to move out ("Move out of Payroll backup"), held to the autonomy
  level like any other move.
- **Default names and empty files** ("New Microsoft Excel Worksheet.xlsx", "Untitled
  document") go to Review, marked "looks empty" when they have no contents.
- When AI is on, it receives the folder tree and the topic summaries once per run
  (names only, as the privacy settings allow) to suggest homes and structure.

### 2. Questions
When the overview can't settle something on its own, SortZen asks before showing the plan,
most important first and at most 10 per run. Each question names what was found and
offers choices, e.g.:

> "Garden Planner" files are in 3 places: My Drive (3), My Drive/Owen Sample (14 files
> and 7 folders) and Documents/Projects (2). What is it?
> ○ A project I'm working on for Owen Sample → Projects/Programming/Owen Sample/Garden Planner
> ○ Owen Sample's own files → My Drive/Owen Sample
> ○ Something else: choose a folder…

Answers become rules (§8). Anything still unsettled goes to Review.

### 3. File by file
For each file, in this order, stopping at the first confident answer:
1. **Rules** written or approved by users, including answers to questions, e.g.
   "Resume → Personal, even if it mentions Example Co." Exceptions beat general rules.
   A topic's home from the overview counts as strong evidence.
2. **Learned examples** (§8): already-sorted files that look like this one, by file type,
   words in the name and words inside the file.
3. **AI** (§9), for what is left, when AI is turned on.
4. **Review**: anything still uncertain.

### Sureness percentage
- Every suggestion for a file or folder carries a **percentage**: how sure SortZen is that
  the destination is right.
- Each percentage can be opened to show **how it was worked out**: every piece of evidence
  for and against, and the runner-up destination. For example:

  > **92% sure → Documents/Word/Work**
  > + Mentions "Example Co.", like 14 of the 15 files in Work
  > + Word document, like all files in Work
  > + Name is like "Safety Audit 2025-03.docx", moved to Work
  > − 1 similar file is in Word/Personal (runner-up: 6%)

- How it is worked out: each folder's profile is the files already in it. SortZen finds
  the sorted files most like this one (shared words in the name and contents, file type,
  details such as a camera), scores each folder from its closest few files, and adds a
  little when the folder's own name matches. The percentage is how clearly the best
  folder beats the others, lowered when even the best match is weak.
- Limits that keep percentages honest:
  - Only the file type matches: at most 50%.
  - The only similar file in a larger folder looks out of place there: at most 75%.
  - The folder's year differs from the file's ("2022 Audit" for a 2023 file): the folder
    counts for much less, and the reason says so.
  - Files that look out of place count less as examples for their folder.
- In a folder being tidied, an organised folder holds on to its files a little, and a
  file alone in its folder stays.
- A rule written or approved by users counts as 100%; SortZen's own scoring tops out at
  99%.
- The AI's answer is one piece of evidence; the percentage always comes from SortZen's own
  scoring, never from the AI's word alone.
- Percentages are checked against the test folders' answer key: of the files marked 90%,
  about 9 in 10 must be right (ROADMAP alpha test).

### Autonomy level
- A setting, **"Move without asking when at least ___% sure"**, 50–100%, default 90%. A
  switch, "Ask me about everything", turns it off.
- Suggestions at or above the level go to **Ready**, ticked; below it, to **Review**, unticked
  until users choose a destination.
- Ready files still appear in the full plan, and nothing moves until users confirm the
  whole plan once.

## 8. Learning
SortZen learns only from choices made inside SortZen. It does not watch Explorer.
- **First run**: SortZen reads the files already in the destination folders (on the PC
  only) and uses them as examples.
- **Corrections**: when a suggested destination is changed, the choice is saved as an
  example and weighted towards similar files from then on. One correction nudges;
  repeated corrections outweigh other signals.
- **Accepted suggestions** also count, with a lighter weight.
- The AI receives the closest past choices with each batch, so it follows the same
  pattern.
- Learned preferences can be viewed and cleared.

## 9. AI and cost
- Default service: **Gemini**. A drop-down offers Claude, ChatGPT, OpenRouter, Ollama
  (runs on the PC) and Off.
- API keys are stored in Windows Credential Manager, encrypted for the Windows user, and
  never in the program folder, the settings file or the repository.
- The plan is always made on the PC first. "Ask AI about unsure files…" (Plan tab and Plan
  menu) then offers to ask the AI service about the files SortZen couldn't settle: files
  from the folders being sorted that wait in Review. Files users placed themselves, files
  left out and Google link files are never sent.
- Before anything is sent, a window shows how many files will be asked about, what will be
  sent, the estimated cost, the spending cap and the amount spent this month. The service,
  its key and the privacy choice can be set right there.
- Cost target: **no more than $0.25 per 1,000 files**, met by:
  - Local first (§7): the AI only sees files that rules and examples couldn't place.
  - Two passes: the AI first sees the name and folder only; only files it is still less
    than 70% sure about are asked again with content, as the privacy settings allow.
  - Batches of 40 files, so the numbered folder list (with up to three example names per
    folder) and the house rules are sent once per batch.
  - A spending cap: by default $0.25 per 1,000 files in the plan (changeable in Settings).
    SortZen stops before a batch would go over it.
  - Answers are remembered by the file's contents, so the same file is never paid for
    twice, and they count in every later plan at no cost.
- **House rules**: plain-English notes, e.g. "Resumes are personal even if they mention my
  employer", sent with every AI batch.
- An AI answer is one more piece of evidence, shown with its reasons:
  - When it agrees with SortZen, the percentage rises halfway towards 100 at most, scaled
    by how sure the AI was (never above 97%).
  - On its own it counts for at most 70%, so at the usual autonomy level those files still
    wait in Review. It replaces SortZen's own guess only when that guess was less sure.
  - Nothing moves until users confirm, as always.

## 10. Privacy settings
Explained in plain language in the "Ask AI" window and in Settings (what leaves the PC
and when):
- **What leaves the PC**: the names of the files SortZen couldn't place, where they are now,
  and the names of the folders with a few example file names. Very long numbers in names
  (accounts, cards, phones) and email addresses are removed.
- **How much of a file the AI may see**:
  - Name only (the default): most private, least accurate.
  - The beginning of the file: the first 400 words of a document, in the second pass only.
- **Always name only**: folders and words listed in Settings (by default "tax", "bank",
  "passport", "medical", "password"): for those files only the name is ever sent.
- **Image previews**: off by default. When on, a small preview (256 pixels) of pictures
  SortZen can't place is sent in the second pass. Otherwise pictures are sorted by name and
  photo details.
- Numbers (years kept), email addresses and anything that looks like an account or card
  number are removed from text before it is sent.
- With Ollama, nothing leaves the PC; the window says so.

## 11. Review and move
- Files and folders are moved, not copied, after a **review screen** showing the full plan:
  - **Ready**: at or above the autonomy level, grouped by destination, ticked.
  - **Review**: below it, unsure folders included, unticked.
  - Every row shows its percentage and how it was worked out; a kept-together folder is
    one row ("Project 1, 214 files").
  - Destinations change by drop-down or drag; anything can be ticked or unticked.
  - Moving starts only when users confirm: "Move ticked…" first shows a confirmation window
  with the number of files and kept-together folders, every destination (new folders
  marked), names already taken, folders that will be left empty and removed, and rows
  with problems.
- Files are never overwritten: a name clash becomes `name (2).ext`; a name that already
  ends in a number counts on (`name (2).ext` becomes `name (3).ext`).
- On the same drive, a normal move. To another drive: copy under a temporary name, check
  every copied file matches the original byte for byte, give the copy its real name, then
  delete the original. If a check fails, the original stays.
- Google link files only move within their own drive.
- A file that can't be moved (open in another program, no permission, gone) is skipped;
  the rest carry on, and the result window lists what was skipped and why. Stop safely
  finishes the current file and leaves the rest where they are.
- Every run is logged step by step as it happens, so even an interrupted run can be put
  back. **Undo** (Ctrl+Z, "Undo this move" in the result window, or Edit › Undo a move…
  for any earlier run) puts back a whole run: files return under their original names,
  new folders the run made are removed again, and removed folders are recreated. A
  file whose old name has been taken since gets a number added; nothing is overwritten.
- Subfolders emptied by "sort the inside" are removed once no files are left in them.
- After a move the plan is made again from where everything is now; moved files are
  remembered at their new place, so they aren't read again.
- The plan can be exported to Excel: every file and folder with its destination,
  percentage and reasons.

### Copies
- While making the plan, SortZen finds exact copies: files with the same size and contents
  (by fingerprint), wherever they are in the added folders. Left-out files, cloud-only
  files, Google link files and empty files are never counted.
- The Copies tab lists each set of copies with its folder, date and size; columns sort by
  clicking, and a search box filters names and folders.
- One copy of each set is kept, and the tab says why. The copy kept is the one in an
  organised place (a destination folder, then a subfolder that stays or is kept
  together), then one without a copy number in its name ("name (1)", "name - Copy"), then
  the oldest, then the one with the shortest path. Right-click › "Keep this copy instead"
  chooses another. One copy of every set is always kept.
- Extras are ticked, except copies inside a folder that is kept together. "Queue ticked for
  deletion…" confirms first, then moves the ticked extras into a folder named "Queued for
  deletion YYYY-MM-DD" inside the added folder they are in, keeping their subfolders.
- Right before each extra moves, it is checked byte for byte against the copy kept;
  anything that is no longer an exact copy stays where it is and is listed.
- Nothing is deleted: users delete the "Queued for deletion" folders themselves when they
  are sure. Those folders are never read or sorted. Undo puts the copies back.

## 12. Renaming
- A separate button and screen, offered after sorting is done, and skippable.
- Suggested names (e.g. `2026-10-02 Invoice - Example Co.pdf`) are shown first; nothing is
  renamed until confirmed; Undo works as for moves.

## 13. Install and updates
- Per-user install, no administrator rights needed.
- The program is not code-signed: Windows shows "Windows protected your PC" on first
  install ("More info → Run anyway").
- An in-app updater installs new versions without that warning appearing again.

## 14. Alpha versions
- **0.1, plan only**: scanning, the overview, questions and the full plan with every
  percentage and its reasons. Nothing is moved; corrections are still learned.
  - Folders are added from the toolbar, the File menu, the folder tree (right-click) or the
    Start tab, which also offers the standard Windows folders as destinations.
  - While a plan is made, a window shows a small animation, one progress bar across all
    folders, the current step ("Listing files in older downloads: 850 found"), time so far
    and a time estimate, rotating tips, and Stop safely. The estimate comes from a quick
    count of the files (nothing is opened) and from how fast earlier runs were.
  - The **Folders** tab lists every added folder with its files and size, the time a plan
    will take (from a quick count; nothing is opened), and warnings: very large
    subfolders, files over 500 MB, folders on Google Drive, and a suggestion to close other
    programs or use "Be gentle with my computer" for long runs. Folders expand into
    subfolders and files (folders first), loaded as they are opened.
  - **Tick boxes**: everything starts ticked. An unticked file or folder is left exactly
    where it is: nothing moves into or out of it, and its files are not suggested anywhere.
    SortZen still reads it and learns from it; a file most like the files in a left-out
    folder waits in Review ("Most like the files in 2022 Audit, which is left out"). A
    folder with something left out inside shows a half tick. Also on right-click ("Leave
    out", "Include again"); Undo works.
  - Advanced setting, on by default: "Stop reading left-out folders once SortZen has
    learned enough from them". A left-out folder with at least 100 files already read, and
    new files no more than a quarter of those, has its new files read by name only.
  - Every list sorts by any column: click a heading, click again to reverse. Names sort in
    natural order ("file 2" before "file 10"); numbers, sizes and percentages as numbers.
  - The **Questions** tab lists what SortZen couldn't settle; answers are saved and the plan
    is updated.
  - The **Plan** tab groups everything into Ready, Review, Staying and "Sorted from the
    inside" (messy folders), with the autonomy level and "Ask me about everything" at the
    top; changing them regroups the plan at once. Selecting a row shows how its
    percentage was worked out.
  - The Plan tab's columns are Name, Type (PDF, Word, Folder …), Sure, From, To and Notes,
    each sortable. A search box filters by name, folder or topic; a drop-down shows one
    added folder; "Only rows with problems" shows just those. "Group by" switches between
    Ready and Review and **Destination folder** ("Work/Payroll (42)").
  - **Problems before moving**, in Notes and in the explanation: a new path too long for
    Windows, a file of the same name already there (it would be saved as "name (2)"), and
    destination folders SortZen can't write to.
  - An accuracy line: "So far you changed 3 of 312 Ready suggestions (99% right)".
  - Every row that would move has a tick box: Ready rows start ticked, Review rows
    unticked (ticked once users choose a destination). "Move ticked…" moves them (§11).
  - "Change destination…" and "Leave it where it is" (buttons and right-click, for one or
    several files) are remembered at once; "Update plan" lets SortZen learn from them for
    similar files. Every change can be undone (Ctrl+Z).
- **0.2**: everything in 0.1, plus speed work, the Folders tab, duplicates review, the AI
  step, the Settings window, profiles, and moving files and folders after the plan is
  confirmed, with Undo.
- Not in the alpha: renaming (§12), the in-app updater (§13), rule suggestions (SortZen
  offering "Make this a rule?" after repeated corrections), a privacy option that sends a
  random sample of words, new folders more than one level deep (questions can still choose
  deeper ones), permanently deleting queued files from inside SortZen, reading scanned
  PDFs (OCR), sorting on a schedule.
