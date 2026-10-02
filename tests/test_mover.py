import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sortzen.mover import Mover, MoveRequest
from sortzen.mover import mover as mover_module
from sortzen.tasks import CancelToken


def write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class MoverTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.mover = Mover(self.root / "runs")
        self.downloads = self.root / "Downloads"
        self.sorted = self.root / "Sorted"

    def tearDown(self):
        self.dir.cleanup()

    def test_move_into_new_folder_and_undo(self):
        a = write(self.downloads / "Hartwell lease.pdf", "lease")
        result = self.mover.run([MoveRequest(str(a), str(self.sorted / "Home" / "Lease"))])
        self.assertEqual((result.moved, result.failed), (1, []))
        moved = self.sorted / "Home" / "Lease" / "Hartwell lease.pdf"
        self.assertEqual(moved.read_text(encoding="utf-8"), "lease")
        self.assertFalse(a.exists())
        undone = self.mover.undo(result.log)
        self.assertEqual(undone.moved, 1)
        self.assertEqual(a.read_text(encoding="utf-8"), "lease")
        self.assertFalse((self.sorted).exists())            # folders the run made are gone again

    def test_name_clash_gets_a_number_and_never_overwrites(self):
        write(self.sorted / "notes.txt", "already there")
        a = write(self.downloads / "notes.txt", "new")
        result = self.mover.run([MoveRequest(str(a), str(self.sorted))])
        self.assertEqual(result.renamed, [("notes.txt", "notes (2).txt")])
        self.assertEqual((self.sorted / "notes.txt").read_text(encoding="utf-8"), "already there")
        self.assertEqual((self.sorted / "notes (2).txt").read_text(encoding="utf-8"), "new")

    def test_numbered_names_count_on(self):
        write(self.sorted / "list (2).docx")
        write(self.sorted / "Trip v1.2" / "a.txt")
        self.assertEqual(mover_module.free_name(str(self.sorted), "list (2).docx"), "list (3).docx")
        self.assertEqual(mover_module.free_name(str(self.sorted), "Trip v1.2", is_folder=True), "Trip v1.2 (2)")

    def test_undo_restores_the_original_name(self):
        write(self.sorted / "notes.txt", "already there")
        a = write(self.downloads / "notes.txt", "new")
        result = self.mover.run([MoveRequest(str(a), str(self.sorted))])
        self.mover.undo(result.log)
        self.assertEqual(a.read_text(encoding="utf-8"), "new")
        self.assertFalse((self.sorted / "notes (2).txt").exists())

    def test_folder_moves_whole_and_not_inside_itself(self):
        project = self.downloads / "Kestrel bid"
        write(project / "drawings" / "plan.pdf")
        write(project / "budget.xlsx")
        inside = self.mover.run([MoveRequest(str(project), str(project / "drawings"))])
        self.assertEqual(inside.moved, 0)
        self.assertIn("inside itself", inside.failed[0][1])
        result = self.mover.run([MoveRequest(str(project), str(self.sorted / "Projects"))])
        self.assertEqual(result.moved, 1)
        self.assertTrue((self.sorted / "Projects" / "Kestrel bid" / "drawings" / "plan.pdf").exists())
        self.mover.undo(result.log)
        self.assertTrue((project / "budget.xlsx").exists())

    def test_other_drive_copies_checks_then_removes(self):
        a = write(self.downloads / "photo.jpg", "pixels")
        folder = self.downloads / "Trip"
        write(folder / "day1.jpg", "one")
        drives = lambda path: 2 if str(self.sorted) in path else 1
        with mock.patch.object(mover_module, "_drive", drives):
            result = self.mover.run([MoveRequest(str(a), str(self.sorted)), MoveRequest(str(folder), str(self.sorted))])
        self.assertEqual(result.moved, 2)
        self.assertFalse(a.exists())
        self.assertFalse(folder.exists())
        self.assertEqual((self.sorted / "photo.jpg").read_text(encoding="utf-8"), "pixels")
        self.assertEqual((self.sorted / "Trip" / "day1.jpg").read_text(encoding="utf-8"), "one")
        self.assertEqual([p.name for p in self.sorted.iterdir() if p.name.endswith(mover_module.PART)], [])

    def test_copy_that_does_not_match_keeps_the_original(self):
        a = write(self.downloads / "photo.jpg", "pixels")
        hashes = iter(["aaa", "bbb"])
        with mock.patch.object(mover_module, "_drive", lambda path: 2 if str(self.sorted) in path else 1), \
                mock.patch.object(mover_module, "_hash", lambda path: next(hashes)):
            result = self.mover.run([MoveRequest(str(a), str(self.sorted))])
        self.assertEqual(result.moved, 0)
        self.assertIn("didn't match", result.failed[0][1])
        self.assertTrue(a.exists())
        self.assertEqual(os.listdir(self.sorted), [])

    def test_file_in_use_is_skipped_and_the_rest_carry_on(self):
        a = write(self.downloads / "open.docx")
        b = write(self.downloads / "closed.docx")
        real = os.rename

        def rename(src, dst):
            if src.endswith("open.docx"):
                raise PermissionError("in use")
            return real(src, dst)

        with mock.patch.object(mover_module.os, "rename", rename):
            result = self.mover.run([MoveRequest(str(a), str(self.sorted)), MoveRequest(str(b), str(self.sorted))])
        self.assertEqual(result.moved, 1)
        self.assertIn("open in another program", result.failed[0][1])
        self.assertTrue(a.exists())
        self.assertTrue((self.sorted / "closed.docx").exists())

    def test_google_links_stay_on_their_drive(self):
        link = write(self.downloads / "Budget.gsheet", "{}")
        with mock.patch.object(mover_module, "_drive", lambda path: 2 if str(self.sorted) in path else 1):
            result = self.mover.run([MoveRequest(str(link), str(self.sorted))])
        self.assertEqual(result.moved, 0)
        self.assertIn("Google link", result.failed[0][1])
        self.assertTrue(link.exists())

    def test_emptied_folders_removed_and_recreated_on_undo(self):
        messy = self.downloads / "older downloads"
        a = write(messy / "deep" / "a.txt")
        b = write(messy / "b.txt")
        keep = write(self.downloads / "still here" / "c.txt")
        result = self.mover.run([MoveRequest(str(a), str(self.sorted)), MoveRequest(str(b), str(self.sorted))],
                                remove_if_empty=[str(messy), str(keep.parent)])
        self.assertEqual(result.removed_folders, 2)
        self.assertFalse(messy.exists())
        self.assertTrue(keep.exists())
        self.mover.undo(result.log)
        self.assertTrue(a.exists())
        self.assertTrue(b.exists())

    def test_undo_twice_is_refused_and_runs_are_listed(self):
        a = write(self.downloads / "a.txt")
        first = self.mover.run([MoveRequest(str(a), str(self.sorted))])
        b = write(self.downloads / "b.txt")
        second = self.mover.run([MoveRequest(str(b), str(self.sorted))], kind="duplicates")
        runs = self.mover.runs()
        self.assertEqual([r["log"] for r in runs], [second.log, first.log])
        self.assertEqual(runs[0]["kind"], "duplicates")
        self.mover.undo(first.log)
        with self.assertRaises(ValueError):
            self.mover.undo(first.log)
        self.assertTrue(self.mover.runs()[1]["undone"])

    def test_undo_never_overwrites_a_new_file_with_the_same_name(self):
        a = write(self.downloads / "a.txt", "original")
        result = self.mover.run([MoveRequest(str(a), str(self.sorted))])
        write(self.downloads / "a.txt", "downloaded again")
        undone = self.mover.undo(result.log)
        self.assertEqual(undone.renamed, [("a.txt", "a (2).txt")])
        self.assertEqual((self.downloads / "a.txt").read_text(encoding="utf-8"), "downloaded again")
        self.assertEqual((self.downloads / "a (2).txt").read_text(encoding="utf-8"), "original")

    def test_stop_safely_leaves_the_rest_in_place(self):
        files = [write(self.downloads / f"{i}.txt") for i in range(3)]
        token = CancelToken()
        events = []

        def emit(event):
            events.append(event)
            if len(events) == 2:
                token.cancel()

        result = self.mover.run([MoveRequest(str(f), str(self.sorted)) for f in files], emit=emit, token=token)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.moved, 1)
        self.assertTrue(files[2].exists())

    def test_missing_file_reported_plainly(self):
        result = self.mover.run([MoveRequest(str(self.downloads / "gone.txt"), str(self.sorted))])
        self.assertIn("no longer there", result.failed[0][1])


if __name__ == "__main__":
    unittest.main()
