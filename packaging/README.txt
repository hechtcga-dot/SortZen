SortZen 0.2 - README
====================

SortZen sorts messy folders, such as Downloads or a cloud drive, into the right folders.
It reads your files on this PC, learns from the folders you've already sorted, shows how
sure it is about every suggestion and why, and moves files only after you confirm.
Every move can be undone.


Installing
----------
1. Run SortZen-Setup-0.2.2.exe. No administrator rights are needed; SortZen installs for
   your Windows account only (in %LOCALAPPDATA%\Programs\SortZen). Installing over 0.1
   or 0.2 keeps your settings, answers and choices.
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
5. Questions: answer what SortZen couldn't settle on its own. Answers are remembered.
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


What's new in 0.2
-----------------
Fixes in 0.2.2:
- The window shown while SortZen works keeps each tip up for 20 seconds, has a "Next"
  button, and mixes in a few "Did you know?" facts.

Fixes in 0.2.1:
- The AI model is picked from a drop-down list (or typed); "Get the list from ..." shows
  the models the service offers, and "Check" tries the service, model and key.
- A wrong model name, a refused key or an unreachable service is explained in a message,
  and the "Ask AI" window stays open to fix it, instead of closing.

- Moving: ticked files and folders move after a confirmation window, never overwriting
  anything. Every move is logged and can be undone, even later (Edit > Undo a move...).
- Copies tab: exact copies, the copy to keep and why, and a dated "Queued for deletion"
  folder for the extras. Nothing is deleted.
- Ask AI about unsure files: two passes, privacy settings, an estimated cost before
  anything is sent, a spending cap ($0.25 per 1,000 files by default), and answers
  remembered so the same file is never paid for twice.
- Folders tab: drill down, untick what to leave alone, file counts, a time estimate and
  warnings.
- Plan: search, filter by folder, group by destination, problems before moving, an
  accuracy readout, tick boxes, and every column sortable.
- A loading window with an animation, the time left and tips; plans are several times
  faster; "Be gentle with my computer".
- Settings window (General, AI, Privacy, Advanced), File > Save and Load profile,
  Help > activity log and diagnostic info.
