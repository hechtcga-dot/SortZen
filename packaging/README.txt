SortZen 0.5 - README
====================

SortZen sorts messy folders, such as Downloads or a cloud drive, into the right folders.
It reads your files on this PC, learns from the folders you've already sorted, shows how
sure it is about every suggestion and why, and moves files only after you confirm.
Every move can be undone.


Installing
----------
1. Run SortZen-Setup-0.5.0.exe. No administrator rights are needed; SortZen installs for
   your Windows account only (in %LOCALAPPDATA%\Programs\SortZen). Installing over an
   earlier version keeps your settings, answers and choices.
2. SortZen isn't code-signed yet. If your browser blocks SortZen-Setup-0.5.0.exe, download
   SortZen-Setup-0.5.0.zip instead, open it and run the setup file inside (in Chrome you can
   also open the downloads list and choose "Keep"). Windows may then show "Windows
   protected your PC": click "More info", then "Run anyway". This happens once per download.


Using it
--------
1. Add a folder to sort (toolbar, File menu, right-click in the folder tree, or the Start
   tab). Choose how:
   - Sort into other folders: for folders like Downloads. Files and subfolders go to your
     destination folders.
   - Tidy this folder: for folders like a cloud drive. Organised subfolders stay where they
     are; loose files and messy subfolders are sorted into them.
2. Add destination folders, or click "Use my Windows folders" (Documents, Pictures, Music,
   Videos).
3. Folders tab: see every added folder with its files and size, how long a plan will take,
   and warnings about very big folders or files. Untick anything SortZen should leave
   exactly where it is; it still learns from it.
4. Click "Start cataloguing" (Ctrl+L). The cataloguing wizard opens:
   - Step 1: make your labels, words for what files are about (Work, Taxes, School, Photo
     session...). Drag them into order: the top label counts most. "Ask AI to suggest
     labels..." proposes some from your file names. Then choose: SortZen labels the files on
     this PC (free), or the AI labels a sample and SortZen labels the rest from it.
   - A window shows the progress, the time left and tips. "Stop safely" stops at any time.
   - Step 2: only the files SortZen isn't sure about, in groups one answer settles. Select
     files or a whole group (Shift- or Ctrl-click) and click a label, or "Looks right".
     Right-click to take a label away, write a note about a file, keep a folder together,
     say a file is similar to (or different from) another file, or delete files (they go to
     a "To delete" folder). A meter shows how often SortZen's guess matched yours; "Catalog
     again" uses what it learned, and each round leaves fewer files.
5. "Finish: see the catalog" opens the Cataloguing tab: every folder with its files and the
   files the plan sends there (in italics). Drag a file onto the right folder: the plan
   changes and SortZen learns. Select a file to see why it goes there and write a note.
   Suggestions such as "Files labelled Resume go to Work/Staffing" can be accepted.
6. Plan: every file and folder is in Ready (at or above your level, "Move without asking
   when at least 90% sure"), Review, Staying, or "Sorted from the inside" (messy folders).
   Select a row to see how its percentage was worked out and any problem found before
   moving (a name already taken, a path too long). Search, filter, group by destination
   folder, and click any column heading to sort.
7. Disagree? "Change destination..." or "Leave it where it is" (also on right-click, for
   several files at once). SortZen remembers it and learns from it for similar files.
8. Optional: "Ask AI about unsure files..." asks an AI service (Gemini, Claude, ChatGPT,
   OpenRouter or Ollama) about the files SortZen couldn't place. It shows what will be
   sent and the estimated cost first.
9. Tick what should move and click "Move ticked...". A window shows every destination,
   new folders and names already taken; nothing moves until you confirm.
10. Copies tab: exact copies, with the one to keep in bold and why. Ticked extras move to
    a "To delete" folder; delete those folders yourself when you're sure.
11. Ctrl+Z undoes your last change, including a move. Edit > "Undo a move..." puts back
    any earlier move. "Export to Excel..." saves the whole plan with the reasons.


Your privacy
------------
- SortZen only reads the folders you add, and works on this PC. Nothing is sent anywhere
  unless you use "Ask AI", and then only for files SortZen couldn't place.
- What the AI may see is up to you (Edit > Settings > Privacy): names only (the default),
  or the beginning of a document with numbers and email addresses removed. Folders and
  words you list are always sent by name only. Picture previews are off unless you turn
  them on. With Ollama, nothing leaves this PC.
- API keys are kept in Windows Credential Manager, never in SortZen's files.
- OneDrive and Google Drive files that are only in the cloud are sorted by name and never
  downloaded. Google Docs, Sheets and Forms links only move within their own drive.
- Settings, answers, choices and move logs are kept in %LOCALAPPDATA%\SortZen. When you
  uninstall, SortZen asks whether to remove them and your saved API keys too.


What's new in 0.5
-----------------
- Cataloguing wizard (Start cataloguing, Ctrl+L): labels first, then only the files SortZen
  isn't sure about, in groups one answer settles. Labels can come from SortZen on this PC
  or from the AI for a sample of files (SortZen labels the rest from it, so it costs much
  less). A meter shows how often SortZen's guess matches yours; each "Catalog again"
  round leaves fewer files.
- Labels: several per file, in order of importance. SortZen learns which folders your
  labels belong in and suggests rules such as "Files labelled Taxes go to Documents/Taxes".
  Select several files and give a label to all of them, or take one away from whichever
  of them have it.
- Cataloguing tab (was Catalog): see where every file will go, drag files to the right
  folder to change the plan, and write a note on a file ("this one is for the 2023
  audit"). Files already in a folder can be dragged too, also from Windows Explorer, and
  folders can be added by dropping them there.
- Similar / different: say a file is like another file, or not, and SortZen becomes more
  or less sure of its folder. Nothing moves because of it.
- Files that belong together stay together: subtitles, .nfo files and posters go with
  their movie, cue sheets with their album, .xmp sidecars with their photo, and a folder
  holding one movie is kept whole.
- Delete: right-click, the Delete button or the Delete key moves files into a "To delete"
  folder at once (it asks first until you tick "Don't ask again"). Nothing is really
  deleted until you delete that folder, and Ctrl+Z puts them back.

Also in 0.4
-----------
- Catalog tab: your categories and subcategories as a tree built from your folders, with
  their files, notes, rules and example files. Rename a category, add a subcategory, write
  what belongs in it, give it another folder (for example on a cloud drive), merge it into
  another, or say "Don't put files here". Everything can be undone.
- Feedback on each category: "Looks right", "Too broad: split it", "Too narrow: merge it",
  "Wrong name", or a comment in your own words.
- Suggestions to accept or turn down: SortZen proposes splits, merges and empty categories
  from your feedback, and "Ask AI to review..." asks the AI service for improvements
  (names, counts, notes, a few example names and your feedback are sent; never file
  contents; the cost is shown first).

Programs and models included: the meaning model is potion-base-8M by Minish (MIT licence);
scanned PDF pages are drawn with pypdfium2 (PDFium, BSD/Apache licences).
