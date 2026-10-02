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
  - **Source folders**: the messy folders to sort (e.g. Downloads).
  - **Destination folders**: where files may go (e.g. Documents, Pictures, Videos, Music,
    or any other folder), including all their subfolders.
- First run offers the standard Windows folders as a starting template, located through
  Windows so that folders moved to OneDrive are found correctly.
- Folders can be added or removed at any time. Nothing outside them is read.
- **Subfolders inside a source folder** each get one of three outcomes, with a percentage
  and reasons like files (§7):
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

## 6. Reading files (on the PC, no AI)
- Details: name, type, size, dates, current folder.
- Contents: Word (.docx: text, title, author), PDF (typed text from the first 10 pages,
  title, author), Excel (.xlsx), PowerPoint (.pptx), text and CSV (any common encoding),
  photo details (camera, date taken, size), the names of files inside .zip archives, and
  program details (.exe: product and company, read through Windows).
- PDFs with no typed text are marked as scans (reading them needs OCR, after the alpha).
- Text is kept up to 20,000 characters per file. Files over 50 MB (other than photos,
  archives and programs) are sorted by name and details only.
- A damaged file is still listed and sorted by name and details, with the reason shown.
- Results are remembered per file (path, size, date changed), so a repeat scan of an
  unchanged folder takes seconds. Stop Safely keeps everything scanned so far.
- Each file gets a content fingerprint: small files are hashed whole; large files from
  their size plus samples at the start, middle and end, so big videos are as quick as
  small files. Learning is tied to the fingerprint, not the name, so a file keeps its
  history when it is moved or renamed.

## 7. How SortZen decides
For each file, in this order, stopping at the first confident answer:
1. **Rules** written or approved by users, e.g. "Resume → Personal, even if it mentions
   Example Co." Exceptions beat general rules.
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

- A rule written or approved by users counts as 100%.
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
- **Rule suggestions**: after a few matching corrections, SortZen offers a rule, e.g.
  "Resumes always go to Personal. Make this a rule?"
- The AI receives the closest past choices with each batch, so it follows the same
  pattern.
- Learned preferences can be viewed and cleared.

## 9. AI and cost
- Default service: **Gemini**, using a low-cost "Lite" model. A drop-down offers Claude,
  ChatGPT, OpenRouter, Ollama (runs on the PC) and Off.
- API keys are stored in Windows Credential Manager, encrypted for the Windows user, and
  never in the program folder or the repository.
- Cost target: **no more than $0.25 per 1,000 files**, met by:
  - Local first (§7): the AI only sees files that rules and examples couldn't place.
  - Two passes: the AI first sees the name and folder only; only files it is still unsure
    about get content, as the privacy settings allow.
  - Batches of 30–50 files, so the folder layout, house rules and examples are sent once
    per batch.
  - An estimated cost shown before every run, a spending cap, and replies remembered by
    fingerprint so the same file is never paid for twice.
- **House rules**: plain-English notes, e.g. "Resumes are personal even if they mention my
  employer", sent with every AI batch.

## 10. Privacy settings
Explained in plain language at first setup (what leaves the PC and when), and always
available in Settings:
- **How much of a file the AI may see**:
  - Name only: most private, least accurate.
  - A random sample of words from across the file: reveals little of any one passage.
  - The beginning of the file, up to about 1,000 words: most accurate.
- **Always name only**: folders and words listed in Settings (e.g. "tax", "bank",
  "passport").
- **Image previews**: off by default. When on, a small preview of images SortZen can't
  place is sent. Otherwise images are sorted by name and photo details.
- Numbers, email addresses and anything that looks like an account or card number are
  removed from text before it is sent.
- With Ollama, nothing leaves the PC; the setup screen says so.

## 11. Review and move
- Files and folders are moved, not copied, after a **review screen** showing the full plan:
  - **Ready**: at or above the autonomy level, grouped by destination, ticked.
  - **Review**: below it, unsure folders included, unticked.
  - Every row shows its percentage and how it was worked out; a kept-together folder is
    one row ("Project 1, 214 files").
  - Destinations change by drop-down or drag; anything can be ticked or unticked.
  - Moving starts only when users confirm the plan.
- Files are never overwritten: a name clash becomes `name (2).ext`.
- On the same drive, a normal move. To another drive: copy, check the copy matches, then
  delete the original.
- Every run is logged. **Undo** puts back the whole run, chosen files, or a whole folder.
- Subfolders emptied by "sort the inside" are deleted; Undo recreates them.

## 12. Renaming
- A separate button and screen, offered after sorting is done, and skippable.
- Suggested names (e.g. `2026-10-02 Invoice - Example Co.pdf`) are shown first; nothing is
  renamed until confirmed; Undo works as for moves.

## 13. Install and updates
- Per-user install, no administrator rights needed.
- The program is not code-signed: Windows shows "Windows protected your PC" on first
  install ("More info → Run anyway").
- An in-app updater installs new versions without that warning appearing again.

## 14. Not in the alpha
Renaming (§12), the in-app updater (§13), reading scanned PDFs (OCR), finding duplicates,
sorting on a schedule.
