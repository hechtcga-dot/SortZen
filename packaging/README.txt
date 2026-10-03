SortZen 0.4 - README
====================

SortZen sorts messy folders, such as Downloads or a cloud drive, into the right folders.
It reads your files on this PC, learns from the folders you've already sorted, shows how
sure it is about every suggestion and why, and moves files only after you confirm.
Every move can be undone.


Installing
----------
1. Run SortZen-Setup-0.4.0.exe. No administrator rights are needed; SortZen installs for
   your Windows account only (in %LOCALAPPDATA%\Programs\SortZen). Installing over an
   earlier version keeps your settings, answers and choices.
2. SortZen isn't code-signed yet, so Windows may show "Windows protected your PC".
   Click "More info", then "Run anyway". This happens once per download.


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
4. Click "Make a plan" (F5). A window shows the progress, the time left and tips. A repeat
   run is much quicker because unchanged files are remembered. "Stop safely" stops at any
   time.
5. To place: groups of files with no clear home ("39 PDFs whose names are only numbers")
   go to a folder you pick or type in one go, and SortZen's questions can be answered with
   any folder. Everything is remembered and can be undone.
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
    a dated "Queued for deletion" folder; delete those folders yourself when you're sure.
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


What's new in 0.4
-----------------
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

Also in 0.3
-----------
- To place tab (instead of Questions): files with no clear home in groups, such as
  "39 PDFs whose names are only numbers". Pick or type a folder and "Put them there" sends
  the whole group; "Also files like these in future plans" makes a rule. Questions can be
  answered with any folder.
- Programs are kept whole, and versions and copies of one thing ("Name-1.7.3",
  "Name-windows (4)", "Name (1)") are gathered into one new folder, such as "Name Program".
- Rules: after you send a few files with a word in common to one folder, SortZen offers a
  rule. Rules are listed in Edit > Settings > Rules.
- Recently chosen folders: the last 20 head the Change destination window, and
  right-click > "Move to" sends files there in one click. New folders can be named there,
  and folders can be renamed (planned ones in the plan, existing ones on disk, with Undo).
- Folder notes: right-click a folder > "Write a note about this folder..." and say what
  belongs in it ("pay stubs, T4s, timesheets"). SortZen and the AI use the words.
- Text in scans and pictures is read with the text recognition built into Windows, on this
  PC. Older Word, Excel and PowerPoint files, Outlook and .eml emails, RTF, OpenDocument
  and web pages are read too.
- Matching by meaning, on this PC: a small model finds folders whose files are about the
  same thing, even with no words in common ("pay stub" and "Payroll"). Nothing is sent.
- AI service: models in a drop-down (or typed), "Get the list" and "Check", and plain
  messages when a model name, key or service is wrong.
- The window shown while SortZen works keeps each tip up longer, has a Next button and a
  few "Did you know?" facts.

Programs and models included: the meaning model is potion-base-8M by Minish (MIT licence);
scanned PDF pages are drawn with pypdfium2 (PDFium, BSD/Apache licences).
