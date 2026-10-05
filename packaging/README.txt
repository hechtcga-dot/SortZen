SortZen 0.7 - README
====================

SortZen sorts messy folders, such as Downloads or a cloud drive, into the right folders.
It reads your files on this PC, learns from the folders you've already sorted, shows how
sure it is about every suggestion and why, and moves files only after you confirm.
Every move can be undone.


Installing
----------
1. Run SortZen-Setup-0.7.0.exe. No administrator rights are needed; SortZen installs for
   your Windows account only (in %LOCALAPPDATA%\Programs\SortZen). Installing over an
   earlier version keeps your settings, answers and choices.
2. SortZen isn't code-signed yet. If your browser blocks SortZen-Setup-0.7.0.exe, download
   SortZen-Setup-0.7.0.zip instead, open it and run the setup file inside (in Chrome you can
   also open the downloads list and choose "Keep"). Windows may then show "Windows
   protected your PC": click "More info", then "Run anyway". This happens once per download.


Using it
--------
1. On the start screen, click "Start the wizard" (or File > New organizing session, Ctrl+N).
   A window opens with three steps; your session is saved as you go, so you can close it
   and carry on later from the start screen ("Carry on a session").
2. Step 1 Choose: give the session a name, add the folders to sort (or drop them in from
   Explorer) and choose how:
   - Sort into other folders: for folders like Downloads. Files and subfolders go to your
     destination folders.
   - Tidy in place: for folders like a cloud drive. Organised subfolders stay where they
     are; loose files and messy subfolders are sorted into them.
   Then add where files go ("Use my Windows folders" adds Documents, Pictures, Music and
   Videos). Options: SortZen only (free, on this PC) or an AI service with a spending cap,
   how sure SortZen must be to need no check, and the labels to start with (words for what
   files are about: Work, Taxes, School... click an idea to add it). Advanced: profiles and
   what the AI may see. Next reads your folders; a window shows the progress and the time
   left, and "Stop safely" stops at any time.
3. Step 2 Duplicates: exact copies, the one kept highlighted and the extra copies ticked.
   Choose which copy to keep (the last version saved, the first, the one already in a
   sorted folder, or the shortest name), or right-click a copy to keep it instead. Next
   moves the ticked copies into a "To delete" folder at once; nothing is really deleted
   until you delete that folder, and Ctrl+Z puts them back.
4. Step 3 Catalog: your files one batch at a time, the ones SortZen is surest about first.
   Untick any that don't fit (they come back later), check the labels (click one to take it
   off, add another, or "+ New label") and click "Confirm and next batch". SortZen learns
   after every batch: it settles batches it is now sure of by itself and may suggest
   merging two labels ("Tax" into "Taxes") or a rule ("Files labelled Taxes go to
   Documents/Taxes"). For files it has no guess about, type a label or send them to Review
   without one. Small links let you keep a folder together, write a note, say files don't
   belong together, or delete them.
5. Review: the wizard closes and the Review tab opens. Batch by batch, surest first, see
   where files go in a folder tree (new folders are marked NEW). Drag files onto another
   folder and SortZen learns; make or delete new folders. Select a file to see its labels,
   why it goes there and a note box; select a folder to see its rules. "Confirm and next
   batch" keeps that batch's plan. Nothing moves yet.
6. After the last batch, the Move window shows every destination, new folders and names
   already taken. Click "Move" to move the files; "Back to Review" changes more first.
7. Rules (Edit > Rules...): files that have something in common go to a folder you choose. A rule
   can combine a label, text in the name, a kind of file, an ending and the folder files are in,
   put files in a folder for each year or month, have a name, and be switched off. While you
   make one, SortZen shows which files it would place.
8. Ctrl+Z undoes your last change, including a move. Edit > "Undo a move..." puts back any
   earlier move, even days later.
9. Anywhere files are listed: double-click opens a file; right-click offers Open, Open containing
   folder and Delete (to the "To delete" folder; Ctrl+Z puts it back).
10. Prefer working without the wizard? Every tab (Folders, Labels, Cataloguing, Plan,
   Copies) opens from View > Tabs or "+ Open a tab" beside the tabs. The Plan tab can ask an
   AI service about unsure files and export the plan to Excel.


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


What's new in 0.7
-----------------
- Much quicker: after each batch the next one shows at once while SortZen learns in the
  background; Back is instant; files open without waiting.
- Right-click any file or folder for Open, Open containing folder and Delete; Review has a
  Delete button.
- Recognise files at a glance: when each was downloaded, its size, folder and the website it
  came from, plus its type, title, pages and first words.
- Review: drag folders onto other folders; "Too many folders?" puts look-alike folders (such as
  old versions of a program) together into one folder you name. Folders that move show where
  they go.
- Rules you can shape: several conditions, a folder for each year or month, names, on and off,
  and a preview of the files a rule places (Edit > Rules...). Suggested rules can be changed
  before they are made.
- Fixes: a rule with nothing to match now says it needs a condition; the wizard's step names
  are never cut off; no pause after the plan is made.

Also in 0.6
-----------
- Organizing sessions: a wizard in three steps (Choose, Duplicates, Catalog), then the
  Review tab and one Move window at the end. Sessions have names, are saved as you go and
  can be carried on from the start screen.
- Duplicates are cleared first: choose which copy to keep, and the extra copies go to "To
  delete" right away so they don't clutter the next steps.
- Cataloguing in batches of related files, surest first, so the easy ones are done quickly
  and SortZen has learned the most by the time it reaches the hard ones. It learns after
  every batch, settles batches it is now sure of, and suggests merging labels and rules.
- Review: a clean folder tree for each batch, new folders marked NEW, drag files to change
  the plan, details and rules on the right.
- A new start screen, and every tab can be closed and opened again from View > Tabs.
- Double-clicking a file or folder in any list opens it.
- Fixes: old suggestion cards disappear at once; the move result window shows every renamed
  file; the Folders tab shows how each folder is sorted in full.

Programs and models included: the meaning model is potion-base-8M by Minish (MIT licence);
scanned PDF pages are drawn with pypdfium2 (PDFium, BSD/Apache licences).
