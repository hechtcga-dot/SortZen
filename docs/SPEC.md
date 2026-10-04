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
- Double-clicking a file or folder in any list opens it (a file with its program, a folder
  in Explorer); in trees the arrow expands and collapses. A folder the plan hasn't made yet
  says so in the status bar.
- Every change can be undone (Ctrl+Z and Undo buttons). Optional panels can be shown or
  hidden.
- Features are reachable from the toolbar, the menus, the folder tree and the start
  screen. The start screen leads with the organizing-session wizard (§7.1a) and lists recent
  sessions; "Show this screen when SortZen opens" turns it off.
- Every tab can be closed, and opened again from View › Tabs or "+ Open a tab" beside the
  tabs.
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
- Also read: older Word, Excel and PowerPoint files (.doc, .xls, .ppt: their text and
  title), Outlook emails (.msg) and saved emails (.eml: subject, sender's name, the
  beginning of the message), RTF, OpenDocument (.odt, .ods, .odp) and web pages.
- **Text in scans and pictures** (Settings › General, on by default): scanned PDFs (no
  typed text) and pictures that aren't camera photos, such as screenshots and scans, are
  read with the text recognition built into Windows 10 and 11, on the PC; nothing is sent
  anywhere. A scanned PDF's first page is drawn as a picture first. Each file is read once
  and remembered; files read before this was available are read once more. Without
  Windows text recognition (or its language), files are sorted by name and details.
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
- **Programs** are kept whole: a folder with code (at least 5 code files and 40% of its
  files), setup or project files (`requirements.txt`, `package.json`, a `.sln` …), or a
  built program (a `.exe` with its `.dll` parts) is one unit. Its files are never sorted
  one by one, and topics and questions never reach inside it.
- **Versions and copies** of one thing go together: sibling folders whose names differ
  only by version or copy endings ("Name", "Name-1.7.3", "Name-release-1.3",
  "Name-windows (4)", "Name (1)"), with the zips and installers of the same name beside
  them, are gathered at 90% into one new folder beside them: "Name Program" when one of
  them is a program, otherwise "Name (all copies)". The new folder can be renamed (§11).
- **Misplaced files**: files inside organised folders that clearly belong to another
  topic are suggested to move out ("Move out of Payroll backup"), held to the autonomy
  level like any other move.
- **Default names and empty files** ("New Microsoft Excel Worksheet.xlsx", "Untitled
  document") go to Review, marked "looks empty" when they have no contents.
- When AI is on, it receives the folder tree and the topic summaries once per run
  (names only, as the privacy settings allow) to suggest homes and structure.

- **Matching by meaning** (Settings › General, on by default): a small model on the PC
  (a static embedding model of about 30 MB, bundled with the program; nothing is sent
  anywhere) turns a file's name, title and the start of its text into a meaning, and each
  folder that can receive files into a meaning profile: the average of its files, its name
  and its note. For files SortZen isn't sure about:
  - when the closest folder by meaning is the one SortZen suggests, the percentage rises
    a little ("By meaning, most like what is in “Payroll”"), up to 95%;
  - when SortZen had no good suggestion and one folder is clearly closest, that folder is
    suggested at 65% at most, so the file waits in Review with the reason shown.
  Files users placed, files placed by rules and topic members keep what they have.

### 1a. Organizing sessions: the wizard, then Review
An **organizing session** is one clean-up from start to end, named by users ("Downloads
clean-up, Oct 2026") and saved as it goes, so it can be stopped and carried on. "Start the
wizard" (the start screen), File › New organizing session… (Ctrl+N) and the toolbar open the
**wizard**, a window with three steps; the start screen also lists recent sessions, the
latest used first, with where each one is ("Step 3 Catalog · 85 files done", "Review · batch 4
of 9", "Moved · 273 files") and Open (right-click › Forget this session).

**Step 1 Choose**: the session's name; **Input**, the folders to sort, each sorted into other
folders or tidied in place (added with "Add a folder…" or dropped from Explorer); **Output**,
where files go ("Use my Windows folders", "Add a folder…"); **Options**: SortZen only (free, on
this PC) or an AI service with its spending cap per 1,000 files, match by meaning, read scans,
be gentle, "Move without asking when at least __% sure" (in Review, batches this sure need no
check), the labels to start with (ideas from the names of the destination folders, two levels
down, leaving out general names like Documents or a year; "+ New label"), and "Ask the AI to
suggest starting labels from the file names"; **Advanced**: load or save a profile, and what
the AI may see (privacy). Next reads the folders and makes the plan; with AI chosen, the AI
suggests labels (if asked) and labels a sample of the files, each after showing the cost.

**Step 2 Duplicates** (skipped when there are no exact copies): every set of copies (§11),
the kept one highlighted and marked KEEP, the extras ticked; Select all / Select none; double-
click opens; right-click › "Keep this copy instead". Which copy to keep: the last version saved
(the default), the first version saved, the one already in a sorted folder, or the one with the
shortest name; ties go to a name without a copy number, then the shorter path, and a copy inside
a folder kept together is never ticked. Next moves the ticked extras into "To delete" at once
(each checked byte for byte first), so the next step isn't cluttered; Undo puts them back.
"Skip: keep every copy" moves nothing.

**Step 3 Catalog**: the files being sorted, one **batch** of related files per screen, surest
first, so the easy ones are cleared first and SortZen has learned the most by the time it
reaches the files it knows least about. A batch is files with the same kind of name, a shared
word or files that look alike, then files SortZen would give the same labels and send to the
same folder, then files with no clear label by kind; at most 40 files (bigger ones come in
parts). Its certainty is how sure SortZen is of its labels (70%) and its folder (30%). Files
users labelled before, files that go with another file and topic members are not shown.
- The files have tick boxes (Select all / Select none; double-click opens). "Confirm labels for
  the N ticked files": the suggested labels as buttons with their percent, on unless clicked
  off; any other label, or "+ New label". Confirm gives the ticked files exactly those labels,
  as users' own, and each file checks SortZen's guess; unticked files come back later.
- A batch with no guess shows "SortZen has no guess for these": type a label or pick one, or
  "Send to Review without labels".
- Small links: "Keep their folder together", "Write a note" (for the ticked files), "These
  don't belong together" (they come back later, one by one) and "Delete" (into "To delete").
- "Skip for now": the batch comes back at the end; skipped again, its files go to Review as
  they are. Back undoes the last answer and shows that batch again (on the first batch, it goes
  back to Step 1).
- **Learning as it goes**: after each confirmed batch the labels are guessed again and the
  remaining batches formed again. Once SortZen's guesses matched users' choices in at least 90%
  of at least 20 checks, batches it is at least 85% sure of are settled by themselves ("3 more
  batches (27 files) are now settled and skipped"). It also suggests merging two labels that
  are surely the same ("Tax" into "Taxes": every file and rule follows) and folders for labels
  (§7.2b); each with a button and "Not now".
- The footer shows the files left, the agreement meter ("SortZen matched your choice in 46 of
  your last 50") and how many batches SortZen settled by itself.

After the last batch the wizard closes, the plan is made again with everything learned, and
the **Review** tab opens with the other tabs closed (they open again from View › Tabs or
"+ Open a tab"). Nothing has moved yet, except the copies in Step 2.

**Review**: the files the plan moves, in batches of files with the same labels (split by folder
when there are more than 60), surest first; folders that move as they are form their own
batch. Batches at or above the "Move without asking" level are confirmed by SortZen and can
still be changed.
- Left: a clean folder tree of the folders files can go to, the batch's files under the folder
  they go to, and folders still to be made marked NEW. Dragging files onto another folder
  changes the plan and SortZen remembers it as users' choice; dragging a NEW folder moves it.
  "New folder" makes a folder in the plan inside the selected one (made on disk when files
  move into it); "Delete folder" deletes a folder still to be made, and its files go to the
  folder it was in (folders that exist are deleted in Explorer).
- Right: the selected file's labels, why it goes there and a note box; for a folder, its
  rules ("Files labelled Taxes go to Documents/Taxes") with Remove and "Add a rule…". Rules
  are not shown in the tree.
- "Confirm and next batch" keeps the batch's plan (SortZen remembers each file's folder) and
  shows the next; "Previous batch"; "Skip for now". After the last batch the **Move window**
  shows everything that will move ("All 9 batches reviewed. Move 412 files into 23
  folders?"), new folders, names already taken, and the copies already in "To delete";
  nothing moves before it. Files in skipped batches stay where they are. Every move is
  logged and Undo puts it back. The session is then "Moved" on the start screen.

### 2. Labels: the label list, then only what SortZen isn't sure about
The **Labels** tab (View › Tabs, Ctrl+L) works without a session.

**Step 1: labels.** Users make their label list: words for what files are about ("Work",
"Taxes", "School", "Photo session"). A file can have several labels. The list is ordered by
dragging: the top label counts most when SortZen weighs labels as evidence for a folder (the
bottom one half as much). Labels don't name folders; SortZen learns which folders they belong
in. "Ask AI to suggest labels…" sends up to 200 file names (long numbers removed) and the
destination folder names, after showing the cost, and returns up to 20 labels about what files
are about (never file types such as "PDF" or "Subtitles"), each with a tick box. Then users
choose how files get their first labels:
- **SortZen on this PC** (free): a label's words in a file's name (85%), its folders (70%),
  a note users wrote about it (90%) or its contents (40%, too little on its own to apply a
  label), combined with the labels of the labelled files most like it. A label applies at
  50% or more.
- **The AI for a sample**: up to 300 files spread over every folder are labelled by the AI
  (in batches of 40, within the spending cap, after the cost is shown), and SortZen labels
  the rest on the PC from them.

**Step 2: check.** The plan is made and the wizard lists only the files that need users:
files whose folder SortZen isn't sure of (below the autonomy level), and files given a label
at 50 to 69%. Files no label fits, with a sure folder, need nothing. They are gathered into
groups one answer settles (the same kind of name, a shared word, or files that look alike by
their clues), biggest first, then the other files; files that go with another file (§7.4)
never appear on their own. Users select files or whole groups and:
- click a label to give it (or, when all have it, take it away); with files that differ, a
  label shows how many of them have it ("Work 3/8"), and right-click › "Take a label away"
  (or right-click the label) takes it from whichever of them have it, "Give a label" gives it
  to the rest; "Looks right" keeps the labels shown;
- "Delete…" (button, right-click or the Delete key) moves the files into the "To delete"
  folder in the folder they were added with, at once and out of the list; it asks first
  until "Don't ask again" (Settings › General), and Undo puts them back;
- right-click › "Note about this file…" (§7.5), "Keep “folder” together" (it moves as it
  is), "Similar to another file…" / "Different from another file…" (below), "Put in a
  folder…" (a whole group can also become a rule).

A meter shows how many files need users and how often SortZen's guess matched users'
changes over the last 50 (each label added or taken away, "Looks right" and each folder
chosen is a check). After 10 changes SortZen offers **Catalog again**: the plan is made again
with everything learned, and each round should leave fewer files. "Ask AI about the rest…"
labels only the files SortZen is still unsure of, after showing the cost. When SortZen
matched at least 90% of at least 30 checks, it says the rest can be left to it. "Finish: see
the catalog" opens the Cataloguing tab.

- **Similar to / different from**: evidence, never a move. "Similar to" makes SortZen surer
  when its guess is the other file's folder (halfway towards 100%, at most 95%), leans an
  unsure file (no folder, or under 60%) towards it at 60%, and makes a guess elsewhere less
  sure (80% of its percentage). "Different from" drops a guess for the other file's folder to
  at most 30%, or switches to the runner-up. What was said shows in the Why column and can be
  forgotten.
- Every label, change and note can be undone.
- **Questions**, most important first and at most 10 per run, each with its suggested
  answers and "Another folder:" with the same folder box. Each question names what was
  found and offers choices, e.g.:

> "Garden Planner" files are in 3 places: My Drive (3), My Drive/Owen Sample (14 files
> and 7 folders) and Documents/Projects (2). What is it?
> ○ A project I'm working on for Owen Sample → Projects/Programming/Owen Sample/Garden Planner
> ○ Owen Sample's own files → My Drive/Owen Sample
> ○ Another folder: [pick or type a folder]

Answers are remembered. Anything still unsettled goes to Review.

### 2b. Labels as evidence for folders
Each folder's labels come from the labelled files in it; a file users put in a folder counts
three times. A file's labels, weighted by their priority and sureness, are compared with every
folder that may receive files: when a folder's files carry the same labels (at least half
weighted), a guess for that folder gets surer, and an unsure file (no folder, or under 60%)
leans towards it (up to 95%). Users' choices and rules are never overruled. A rule can be
"Files labelled X go to Y": it is suggested when users put at least 3 files with that label in
one folder (80% of those they put there), and in the Cataloguing tab when a folder holds mostly
files with that label (half or more, at least 3), or as a new folder named after the label
when at least 5 unsure files carry it and they don't mostly lean towards one folder already.
No folder is ever suggested for a file type alone.

### 4. Files that go with another file
Subtitles (.srt, .sub, .idx, .ass, .ssa, .vtt, .smi), .nfo and .thm files go with the movie
in their folder (the one whose name theirs begins with, or the only movie there; samples and
trailers don't count), cue sheets and lyrics with their album, a photo's .xmp or .aae sidecar
with the photo of the same name, and artwork (poster, folder, fanart, cover…) with the movie
or album beside it. They go wherever that file goes, are never grouped, labelled into a folder
or asked about on their own, and never join a topic. A folder holding one movie with only its
subtitles, artwork and small text files (subfolders such as Subs, Sample or Extras allowed)
is kept whole: "One movie (“…”) with the files that go with it".

### 5. Notes on files
A note on a file ("this one is for the 2023 audit") counts for its labels like the file's
name, goes to the AI with the file, and when it names a folder (every word of the folder's
name), sends the file there at 85% ("Your note: …").

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
- The model is chosen from a drop-down or typed by name. "Get the list from …" asks the
  service which models it offers this key and remembers the list; a typed name that isn't
  on it is pointed out. "Check" sends a tiny test request.
- Pressing "Ask" first checks the service, model and key with a tiny request. When that
  fails, the window stays open and says what is wrong in plain words (the service can't
  find the model, didn't accept the key, can't be reached, or is busy) and nothing about
  the files is sent. An error later in a run is shown the same way.
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
  deletion…" confirms first, then moves the ticked extras into a folder named "To delete"
  inside the added folder they are in, keeping their subfolders. In an organizing session,
  Step 2 does the same with the copy kept chosen by a rule (§7.1a).
- Right before each extra moves, it is checked byte for byte against the copy kept;
  anything that is no longer an exact copy stays where it is and is listed.
- Nothing is deleted: users delete the "To delete" folders themselves when they
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
- Uninstalling asks whether to also remove the settings, answers, chosen destinations,
  remembered results, saved API keys and the move logs Undo uses (No is the default).
  Sorted files are never touched. A silent uninstall keeps them.

## Settings, profiles and help
- **Settings** (Edit › Settings…, Ctrl+,), saved when OK is pressed and undoable:
  - General: the autonomy level, "Ask me about everything", "Be gentle with my computer".
  - AI: the service, its model and its key (§9).
  - Privacy: name only or the beginning of the file, picture previews, name-only folders
    and words, house rules, the spending cap per 1,000 files, the amount spent this month,
    and "Forget remembered AI answers" (§10).
  - Advanced: "Stop reading left-out folders once SortZen has learned enough from them"
    (on by default) and "Read file contents on Google Drive" (off by default).
- **Profiles** (File › Save profile… / Load profile…, `.szprofile`): the added folders,
  left-out items, answers, chosen destinations, autonomy, options, AI and privacy settings
  and house rules. Speeds and spending stay with the PC. Saved API keys are included only
  when users say yes. Loading a profile replaces the current settings (Undo puts them
  back); folders it names that this PC doesn't have can be pointed at their new place or
  left out, and every path inside the profile follows them.
- **Help**: "Open the activity log" (what SortZen did and any problems) and "Copy
  diagnostic info" (version, system, counts and settings, with no file or folder names
  and no keys).

## 14. Alpha versions
- **0.1, plan only**: scanning, the overview, questions and the full plan with every
  percentage and its reasons. Nothing is moved; corrections are still learned.
- **0.2**: everything in 0.1, plus moving files and folders after confirmation with Undo
  (§11), the Copies tab (§11), the AI step (§9, §10), Settings, profiles and help, plans
  several times faster, and:
  - Folders are added from the toolbar, the File menu, the folder tree (right-click) or the
    Start tab, which also offers the standard Windows folders as destinations.
  - While a plan is made, a window shows a small animation, one progress bar across all
    folders, the current step ("Listing files in older downloads: 850 found"), time so far
    and a time estimate, tips that change every 20 seconds (with a Next button and a
    "Did you know?" fact after every two tips), and Stop safely. The estimate comes from a quick
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
- **0.3**: everything in 0.2, plus:
  - **Recently chosen folders**: the 20 folders most recently chosen as destinations are
    remembered. They head the "Change destination" window, and right-click › "Move to"
    sends the selected files to one of them in one click.
  - **New folder…** in the "Change destination" window names a new folder inside the
    selected one; it is made when the files move.
  - **Renaming folders**: "Rename…" in the "Change destination" window, and right-click ›
    "Rename its destination folder…". A folder SortZen only plans to make is renamed in
    the plan, and the name is remembered for later plans. A folder that exists is renamed
    on disk after confirmation, logged like a move so Undo puts the old name back. Choices,
    rules and recent folders that point into it follow the new name.
  - **Folder notes**: right-click a folder on the Folders tab (or a file on the Plan tab,
    for its destination folder) › "Write a note about this folder…" and say what belongs
    in it ("pay stubs, T4s, timesheets"). The words count like words in the folder's name
    ("Your note on “Payroll” mentions “timesheet”"), are sent to the AI service with the
    folder list, and are used for matching by meaning. Notes show in the Folders tab's
    Note column and in the "Change destination" window, are saved in profiles, follow
    renamed folders, and can be undone.
  - **Rules**: a rule sends files whose names contain a word (optionally of one file type)
    to a folder, at 100%. When users send two or more files with a word in common to the
    same folder, SortZen offers a rule ("Names with “invoice” go to Work/Accounts
    Payable? 12 more files in this plan match"), but only when the rule would place other
    files and never when it would overrule a suggestion SortZen is at least 90% sure of.
    "Make a rule and update the plan", "Not now" or "Don't suggest this again". The most
    specific rule wins (a word and a type before a word alone); files users placed
    themselves keep their choice. Rules are listed, and can be removed, in Settings ›
    Rules, are saved in profiles, and making one can be undone.
- **0.4**: everything in 0.3, plus:
  - **Catalog** tab: the categories files are sorted into, as a tree built from the
    destination folders and the folders being tidied, one category per folder, nested like
    the folders; program folders are left out (their files count towards the category
    above). Each category shows its files, folders, note, rules, example files and
    feedback.
  - **Editing**, by buttons and right-click: rename (the name shown, or the folder too),
    add a subcategory (an empty folder with what belongs in it), write a note, add another
    folder (a category can span places, e.g. Documents and a cloud drive), merge into
    another category (future files go there; its files can move too, after confirmation),
    and "Don't put files here" (still learned from, never a destination). Every edit can
    be undone; moves are logged like any move.
  - **Feedback** on each category: "Looks right", "Too broad: split it", "Too narrow:
    merge it", "Wrong name" (with a better name) and comments in users' own words.
  - **Suggestions**, each with Accept and Not this (not suggested again):
    - worked out on the PC: split a category whose own files fall into groups by a word
      they share (30 files or more; 8 after "Too broad"), merge near-duplicate sibling
      names ("Invoice" and "Invoices"), merge after "Too narrow" (into the sibling sharing
      most words, or the category above), and empty categories; nothing for categories
      marked "Looks right";
    - "Ask AI to review…": category names, file counts, notes, up to 4 example names (long
      numbers removed) and users' feedback are sent, never file contents, after the cost
      is shown; the AI suggests renames, merges, splits (subcategories with the words of
      the files that belong in them) and new subcategories.
  - Catalog edits are saved with profiles and follow renamed folders.
- **0.5**: everything in 0.4, plus:
  - **Cataloguing wizard** (§7.2) instead of the To place tab: labels with priority (users',
    SortZen's on the PC, the AI's for a sample), only the files that need users, in groups
    one answer settles, Looks right, notes, kept-together folders, similar / different, an
    agreement meter, rounds of cataloguing again, and labels as evidence for folders (§7.2b).
  - **Cataloguing tab** (the Catalog tab, renamed): each folder's files and the files the
    plan sends there ("Coming", in italics), folders the plan makes ("(new)"). Dragging a
    planned file onto another folder changes the plan (nothing moves) and counts as users'
    choice; "Right folder" agrees with the plan's choice; files already in a folder, several
    at a time, and folders move on disk after confirmation, logged like any move (also from
    Windows Explorer), and are remembered as users' choice; a folder moved into another keeps
    its name, note and settings. Right-click: Labels, Move to a category (recent folders
    first), Delete, Open. A note box for the selected file shows why it goes there. Folders
    for labels are suggested (§7.2b). The Plan tab stays as the final check before moving.
  - **Deleting** moves files into a "To delete" folder in the folder they
    were added with (as for copies); users delete that folder themselves when sure.
  - **Adding folders**: "Add a folder…" (or right-click the empty space below the
    folders), or a folder dropped there from Explorer, adds it to the catalog as a
    destination folder.
  - **Files that go with another file** (§7.4) and **folders that hold one movie** stay whole.
- **0.6**: everything in 0.5, plus:
  - **Organizing sessions** (§7.1a): named and saved as they go, reopened from the start
    screen; the wizard (Choose, Duplicates, Catalog) and the Review tab, then the Move window.
  - The start screen leads with the wizard and lists recent sessions; tabs close and open
    again from View › Tabs and "+ Open a tab".
  - Double-clicking a file or folder in any list opens it.
- Not in the alpha: renaming files (§12), the in-app updater (§13), a privacy option that sends a
  random sample of words, new folders more than one level deep (questions can still choose
  deeper ones), permanently deleting queued files from inside SortZen, reading scanned
  PDFs (OCR), sorting on a schedule.
