SortZen 0.1 - README
====================

SortZen sorts messy folders, such as Downloads or a cloud drive, into the right folders.
It reads your files on this PC, learns from the folders you've already sorted, and shows
how sure it is about every suggestion and why.

Version 0.1 is PLAN ONLY: it shows what it would do and moves nothing, so it is safe to
try on your real folders.


Installing
----------
1. Run SortZen-Setup-0.1.0.exe. No administrator rights are needed; SortZen installs for
   your Windows account only (in %LOCALAPPDATA%\Programs\SortZen).
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
3. Click "Make a plan" (F5). SortZen reads the folders; a repeat run is much quicker
   because unchanged files are remembered. "Stop safely" stops at any time.
4. Questions: answer what SortZen couldn't settle on its own, then "Save answers and
   update the plan". Answers are remembered.
5. Plan: every file and folder is in Ready (at or above your level, "Move without asking
   when at least 90% sure"), Review, Staying, or "Sorted from the inside" (messy folders).
   Select a row to see how its percentage was worked out.
6. Disagree? "Change destination..." or "Leave it where it is" (also on right-click, for
   several files at once). SortZen remembers it; "Update plan" lets it learn from it for
   similar files. Ctrl+Z undoes.
7. "Export to Excel..." saves the whole plan with the reasons.


Your privacy
------------
- SortZen only reads the folders you add. Nothing in this version is sent anywhere; the
  AI step comes in a later version and is optional.
- OneDrive and Google Drive files that are only in the cloud are sorted by name and never
  downloaded. Google Docs, Sheets and Forms links only move within their own drive.
- Settings, answers and choices are kept in %LOCALAPPDATA%\SortZen. Uninstalling keeps
  them; delete that folder to remove them too.


What's new in 0.1
-----------------
- First alpha: folders, the overview (organised, project and messy subfolders, topics
  spread over several places), questions, the plan with percentages and reasons,
  changing destinations, Undo, and export to Excel. Plan only; nothing is moved.
