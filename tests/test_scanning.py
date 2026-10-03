import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from sortzen.repositories.file_index import FileIndex
from sortzen.scanning import readers, scanner as scanner_module
from sortzen.scanning.fingerprint import fingerprint
from sortzen.scanning.scanner import ProtectedFolderError, Scanner
from sortzen.tasks import CancelToken, Progress
from tests.fixtures import answer_key, shared_test_folders
from tests.fixtures.make_test_folders import write_docx, write_jpeg, write_pdf, write_pptx, write_xlsx


class ReadersTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.folder = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def read(self, name, kind):
        path = self.folder / name
        return readers.read_contents(path, kind, path.suffix, path.stat().st_size)

    def test_word(self):
        write_docx(self.folder / "a.docx", "Safety audit", "Avery Lane", "Example Co. safety audit\nSecond line")
        details, text = self.read("a.docx", "word")
        self.assertEqual(details, {"title": "Safety audit", "author": "Avery Lane"})
        self.assertEqual(text, "Example Co. safety audit\nSecond line")

    def test_excel(self):
        write_xlsx(self.folder / "a.xlsx", "Budget", "Jordan", [["Item", "Amount"], ["Rent", "1650"]])
        details, text = self.read("a.xlsx", "spreadsheet")
        self.assertEqual(details["sheets"], 1)
        self.assertEqual(text.split("\n"), ["Item", "Amount", "Rent", "1650"])

    def test_powerpoint_slides_in_order(self):
        write_pptx(self.folder / "a.pptx", "Kickoff", "Avery", [[f"Slide {i}"] for i in range(1, 12)])
        details, text = self.read("a.pptx", "presentation")
        self.assertEqual(details["slides"], 11)
        self.assertEqual(text.split("\n")[:3], ["Slide 1", "Slide 2", "Slide 3"])
        self.assertEqual(text.split("\n")[-1], "Slide 11")

    def test_pdf(self):
        write_pdf(self.folder / "a.pdf", ["Maple Grocery", "Total paid $12.50"], title="Maple Grocery receipt")
        details, text = self.read("a.pdf", "pdf")
        self.assertEqual(details["pages"], 1)
        self.assertEqual(details["title"], "Maple Grocery receipt")
        self.assertIn("Total paid $12.50", text)

    def test_pdf_without_text_is_marked(self):
        write_pdf(self.folder / "scan.pdf", [])
        details, text = self.read("scan.pdf", "pdf")
        self.assertTrue(details["no_text"])
        self.assertEqual(text, "")

    def test_text_encodings(self):
        for encoding in ("utf-8", "utf-16", "cp1252"):
            (self.folder / "n.txt").write_text("café list\r\nmilk\rend", encoding=encoding, newline="")
            self.assertEqual(self.read("n.txt", "text")[1], "café list\nmilk\nend", encoding)

    def test_photo_details(self):
        import random
        write_jpeg(self.folder / "IMG_1.JPG", random.Random(1), ("Pixelcam", "PX-9"), "2025:07:14 10:22:00")
        details, _ = self.read("IMG_1.JPG", "image")
        self.assertEqual(details["camera"], "Pixelcam PX-9")
        self.assertEqual(details["taken"], "2025:07:14 10:22:00")

    def test_zip_names(self):
        import zipfile
        with zipfile.ZipFile(self.folder / "a.zip", "w") as z:
            z.writestr("photos/one.jpg", b"1")
            z.writestr("photos/two.jpg", b"2")
        details, _ = self.read("a.zip", "archive")
        self.assertEqual(details, {"files": 2, "names": ["photos/one.jpg", "photos/two.jpg"]})

    def test_text_is_capped(self):
        (self.folder / "big.txt").write_text("word " * 10_000, encoding="utf-8")
        self.assertLessEqual(len(self.read("big.txt", "text")[1]), readers.MAX_TEXT_CHARS)

    @unittest.skipUnless(os.name == "nt", "program details are read through Windows")
    def test_program_details(self):
        import sys
        path = Path(sys.executable)
        details = readers.read_contents(path, "installer", ".exe", path.stat().st_size)[0]
        self.assertIn("Python", details.get("product", "") + details.get("company", ""))


class FingerprintTest(unittest.TestCase):
    def test_same_content_same_fingerprint_any_name(self):
        with tempfile.TemporaryDirectory() as d:
            a, b, c = Path(d, "a.bin"), Path(d, "b.bin"), Path(d, "c.bin")
            data = os.urandom(500_000)
            a.write_bytes(data)
            b.write_bytes(data)
            c.write_bytes(data[:-1] + b"x")
            self.assertEqual(fingerprint(a), fingerprint(b))
            self.assertNotEqual(fingerprint(a), fingerprint(c))


class ScannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = shared_test_folders()
        cls.answer_key = answer_key()
        cls.loose_downloads = [rel for rel in cls.answer_key["files"] if rel.count("/") == 1
                               and rel.startswith("Downloads/")]

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.work = Path(self.dir.name)
        self.index = FileIndex(self.work / "sortzen.db")
        self.scanner = Scanner(self.index, protected=[])

    def tearDown(self):
        self.dir.cleanup()

    def folder(self, name="Downloads"):
        path = self.work / name
        path.mkdir(exist_ok=True)
        return path

    def test_scans_the_whole_test_downloads(self):
        events = []
        summary = self.scanner.scan(self.fixture / "Downloads", "source", recursive=False, emit=events.append)
        self.assertEqual(sorted("Downloads/" + r.name for r in summary.files), sorted(self.loose_downloads))
        self.assertEqual(summary.read, len(self.loose_downloads))
        self.assertEqual(summary.skipped, {"subfolder": 3})
        self.assertIsInstance(events[-1], Progress)
        self.assertEqual(events[-1].done, events[-1].total)
        by_name = {r.name: r for r in summary.files}
        self.assertIn("Prairie Ridge School Division", by_name["Jordan Sample Resume 2025.docx"].text)
        self.assertTrue(by_name["1DXPB0.PDF"].details["no_text"])
        self.assertTrue(all(r.fingerprint for r in summary.files))
        self.assertEqual([r.name for r in summary.files if r.error], [])

    def test_google_link_files(self):
        summary = self.scanner.scan(self.fixture / "My Drive", "source", recursive=False)
        google = [r for r in summary.files if r.ext in (".gdoc", ".gsheet", ".gform")]
        self.assertGreaterEqual(len(google), 10)
        forms = next(r for r in google if r.name == "Blank Quiz.gform")
        self.assertEqual((forms.kind, forms.details, forms.text), ("form", {"google": "Google Forms"}, ""))
        sheet = next(r for r in google if r.name == "Overview of Human Digestive System.gsheet")
        self.assertEqual(sheet.kind, "spreadsheet")
        self.assertFalse(any("@" in str(r.details) + r.text for r in google))       # the account email is not kept

    def test_destinations_are_scanned_with_subfolders(self):
        summary = self.scanner.scan(self.fixture / "Sorted", "destination", recursive=True)
        self.assertEqual(len(summary.files), sum(1 for p in (self.fixture / "Sorted").rglob("*") if p.is_file()))
        self.assertTrue(any(os.sep.join(("Work", "Payroll")) in r.path for r in summary.files))

    def test_source_subfolders_are_counted_not_entered(self):
        downloads = self.folder()
        (downloads / "extracted").mkdir()
        (downloads / "extracted" / "inner.txt").write_text("x")
        (downloads / "top.txt").write_text("y")
        summary = self.scanner.scan(downloads, "source", recursive=False)
        self.assertEqual([r.name for r in summary.files], ["top.txt"])
        self.assertEqual(summary.skipped, {"subfolder": 1})

    def test_never_sorted_files(self):
        downloads = self.folder()
        for name in ("desktop.ini", "Thumbs.db", "~$report.docx", "movie.mp4.crdownload", "big.iso.part",
                     ".hidden", "keep.pdf"):
            (downloads / name).write_bytes(b"x")
        summary = self.scanner.scan(downloads, "source", recursive=False)
        self.assertEqual([r.name for r in summary.files], ["keep.pdf"])
        self.assertEqual(summary.skipped, {"system": 2, "temporary": 3, "hidden": 1})

    def test_damaged_file_is_listed_with_reason(self):
        downloads = self.folder()
        (downloads / "broken.docx").write_bytes(b"not a zip")
        record = self.scanner.scan(downloads, "source", recursive=False).files[0]
        self.assertEqual(record.kind, "word")
        self.assertIn("Couldn't read the contents", record.error)
        self.assertTrue(record.fingerprint)

    def test_second_scan_reads_nothing_unchanged(self):
        downloads = self.fixture / "Downloads"
        self.scanner.scan(downloads, "source", recursive=False)
        with mock.patch.object(scanner_module, "read_contents", side_effect=AssertionError("read again")):
            summary = self.scanner.scan(downloads, "source", recursive=False)
        self.assertEqual((summary.read, summary.remembered), (0, len(self.loose_downloads)))
        resume = next(r for r in summary.files if r.name == "Jordan Sample Resume 2025.docx")
        self.assertIn("Prairie Ridge School Division", resume.text)

    def test_changed_added_and_removed_files(self):
        downloads = self.folder()
        (downloads / "a.txt").write_text("one")
        (downloads / "b.txt").write_text("two")
        self.scanner.scan(downloads, "source", recursive=False)
        (downloads / "a.txt").write_text("one changed")
        (downloads / "b.txt").unlink()
        (downloads / "c.txt").write_text("three")
        summary = self.scanner.scan(downloads, "source", recursive=False)
        self.assertEqual({r.name: r.text for r in summary.files}, {"a.txt": "one changed", "c.txt": "three"})
        self.assertEqual((summary.read, summary.remembered), (2, 0))
        self.assertEqual([r.name for r in self.index.records(downloads)], ["a.txt", "c.txt"])

    def test_moved_file_keeps_its_fingerprint(self):
        downloads, documents = self.folder(), self.folder("Documents")
        (downloads / "plan.txt").write_text("trip plan")
        before = self.scanner.scan(downloads, "source", recursive=False).files[0].fingerprint
        (downloads / "plan.txt").rename(documents / "renamed plan.txt")
        self.scanner.scan(downloads, "source", recursive=False)
        self.scanner.scan(documents, "destination", recursive=True)
        found = self.index.with_fingerprint(before)
        self.assertEqual([Path(r.path).name for r in found], ["renamed plan.txt"])

    def test_cloud_only_files_are_not_opened(self):
        downloads = self.folder()
        (downloads / "cloud.docx").write_bytes(b"would download")
        real_stat = os.DirEntry.stat

        def cloud_stat(entry, follow_symlinks=True):
            st = real_stat(entry, follow_symlinks=follow_symlinks)
            return SimpleNamespace(st_size=st.st_size, st_mtime_ns=st.st_mtime_ns, st_file_attributes=0x400000)

        with mock.patch.object(os.DirEntry, "stat", cloud_stat), \
                mock.patch.object(scanner_module, "fingerprint", side_effect=AssertionError("opened")), \
                mock.patch.object(scanner_module, "read_contents", side_effect=AssertionError("opened")):
            record = self.scanner.scan(downloads, "source", recursive=False).files[0]
        self.assertTrue(record.cloud_only)
        self.assertIsNone(record.fingerprint)
        self.assertEqual(record.kind, "word")

    def test_excluded_folder_inside_destination(self):
        documents = self.folder("Documents")
        (documents / "Downloads").mkdir()
        (documents / "Downloads" / "x.txt").write_text("x")
        (documents / "y.txt").write_text("y")
        summary = self.scanner.scan(documents, "destination", recursive=True, exclude=[documents / "Downloads"])
        self.assertEqual([r.name for r in summary.files], ["y.txt"])

    def test_protected_folders_refused(self):
        windows = self.folder("Windows")
        with self.assertRaises(ProtectedFolderError):
            Scanner(self.index, protected=[str(windows)]).scan(windows / ".." / "Windows", "source", recursive=False)

    def test_missing_folder_is_a_plain_error(self):
        with self.assertRaises(FileNotFoundError):
            self.scanner.scan(self.work / "nope", "source", recursive=False)

    def test_stop_safely_keeps_earlier_results(self):
        downloads = self.folder()
        for i in range(60):
            (downloads / f"{i:02d}.txt").write_text(str(i))
        token = CancelToken()

        def emit(event):
            if isinstance(event, Progress) and event.done >= 25:
                token.cancel()

        summary = self.scanner.scan(downloads, "source", recursive=False, emit=emit, token=token)
        self.assertTrue(summary.cancelled)
        self.assertEqual(len(summary.files), 25)
        again = self.scanner.scan(downloads, "source", recursive=False)
        self.assertEqual((again.remembered, again.read), (25, 35))

    def test_repeat_scan_of_1000_files_is_fast(self):
        downloads = self.folder()
        for i in range(1000):
            (downloads / f"note {i:04d}.txt").write_text(f"note number {i}")
        self.scanner.scan(downloads, "source", recursive=False)
        start = time.perf_counter()
        summary = self.scanner.scan(downloads, "source", recursive=False)
        elapsed = time.perf_counter() - start
        self.assertEqual(summary.remembered, 1000)
        self.assertLess(elapsed, 5.0)


class GoogleDriveTest(unittest.TestCase):
    def test_streamed_drive_files_are_not_opened(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "My Drive"
            folder.mkdir()
            (folder / "Budget.xlsx").write_bytes(b"would download")
            scanner = Scanner(FileIndex(Path(d) / "i.db"), protected=[])
            with mock.patch.object(scanner_module, "on_google_drive", return_value=True), \
                    mock.patch.object(scanner_module, "read_contents", side_effect=AssertionError("opened")):
                record = scanner.scan(folder, "source", recursive=False).files[0]
            self.assertTrue(record.cloud_only)
            scanner.read_google_drive = True
            with mock.patch.object(scanner_module, "on_google_drive", return_value=True):
                record = scanner.scan(folder, "source", recursive=False).files[0]
            self.assertFalse(record.cloud_only)

    def test_not_google_drive_elsewhere(self):
        if os.name != "nt":
            self.assertFalse(scanner_module.on_google_drive(tempfile.gettempdir()))


class MoreFileTypesTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.dir = tempfile.TemporaryDirectory()
        self.base = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def read(self, name, data):
        from sortzen.scanning.file_types import kind_of
        from sortzen.scanning.readers import read_contents

        path = self.base / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        ext = path.suffix.lower()
        return read_contents(path, kind_of(ext), ext, path.stat().st_size)

    def test_opendocument(self):
        import io
        import zipfile

        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("content.xml", '<office:document-content xmlns:office="urn:o" xmlns:text="urn:t">'
                                      '<text:p>Quarterly garden budget</text:p><text:p>Seeds and soil</text:p>'
                                      '</office:document-content>')
            z.writestr("meta.xml", '<m xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Garden budget'
                                   '</dc:title><dc:creator>Avery Lund</dc:creator></m>')
        details, text = self.read("budget.odt", out.getvalue())
        self.assertEqual(details, {"title": "Garden budget", "author": "Avery Lund"})
        self.assertIn("Seeds and soil", text)

    def test_rtf(self):
        _, text = self.read("letter.rtf", r"{\rtf1\ansi{\fonttbl{\f0 Arial;}}{\*\generator Wordpad;}"
                                          r"\f0\fs22 Dear Avery,\par Your caf\'e9 order is ready.\par}")
        self.assertIn("Dear Avery,", text)
        self.assertIn("café order is ready.", text)
        self.assertNotIn("Arial", text)
        self.assertNotIn("fs22", text)

    def test_eml_plain_and_html(self):
        plain = ("From: Avery Lund <avery@example.com>\nSubject: Northgate invoice 454\n"
                 "Content-Type: text/plain\n\nPlease find the invoice attached.\n")
        details, text = self.read("mail.eml", plain)
        self.assertEqual(details, {"title": "Northgate invoice 454", "author": "Avery Lund"})
        self.assertIn("invoice attached", text)
        html = ("From: Shop <shop@example.com>\nSubject: Receipt\nContent-Type: text/html\n\n"
                "<html><body><p>Thanks for your <b>order</b></p></body></html>\n")
        _, text = self.read("receipt.eml", html)
        self.assertIn("Thanks for your order", text)
        self.assertNotIn("<p>", text)

    def test_older_office_and_outlook_text(self):
        from unittest import mock

        from sortzen.scanning import readers

        blob = b"\x00\x01" + "Hanlon site plan".encode("utf-16-le") + b"\x00\x00\x07" + b"zz\x01"
        self.assertEqual(readers.ole_strings(blob), "Hanlon site plan")

        class FakeOle:
            streams = {"__substg1.0_0037001F": "Lease renewal".encode("utf-16-le"),
                       "__substg1.0_0C1A001F": "Avery Lund".encode("utf-16-le"),
                       "__substg1.0_1000001E": b"The lease renews in May."}

            def __init__(self, path):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def exists(self, name):
                return name in self.streams

            def openstream(self, name):
                import io
                return io.BytesIO(self.streams[name])

        with mock.patch("olefile.OleFileIO", FakeOle):
            details, text = self.read("lease.msg", b"not really ole")
        self.assertEqual(details, {"title": "Lease renewal", "author": "Avery Lund"})
        self.assertIn("renews in May", text)

    def test_older_reads_of_new_kinds_are_read_again(self):
        from sortzen.scanning.readers import READER_VERSION, needs_reread

        def record(ext, details):
            return SimpleNamespace(ext=ext, kind="", size=1000, cloud_only=False, details=details)

        self.assertTrue(needs_reread(record(".doc", {})))
        self.assertFalse(needs_reread(record(".doc", {"reader": READER_VERSION})))
        self.assertFalse(needs_reread(record(".pdf", {})))

    def test_web_page(self):
        _, text = self.read("page.html", "<html><head><style>p{}</style></head><body>Garden &amp; seeds</body></html>")
        self.assertEqual(text, "Garden & seeds")


class TextRecognitionTest(unittest.TestCase):
    """Scans and pictures of documents are read with text recognition; camera photos are not."""

    class Fake:
        def __init__(self):
            self.pictures = []

        def read(self, png):
            self.pictures.append(png)
            return "Northgate invoice 454 total due"

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.base = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_scanned_pdf_and_screenshot_are_read_camera_photo_is_not(self):
        from PIL import Image

        from sortzen.scanning.readers import read_contents
        from tests.fixtures.make_test_folders import write_pdf

        scan = self.base / "48213.pdf"
        write_pdf(scan, [])                                  # a page with no typed text
        fake = self.Fake()
        details, text = read_contents(scan, "pdf", ".pdf", scan.stat().st_size, fake)
        self.assertTrue(details["ocr"])
        self.assertIn("Northgate invoice", text)
        self.assertTrue(fake.pictures[0].startswith(b"\x89PNG"))
        shot = self.base / "Screenshot 2024-05-01.png"
        Image.effect_noise((400, 300), 60).convert("RGB").save(shot)
        details, text = read_contents(shot, "image", ".png", shot.stat().st_size, fake)
        self.assertIn("Northgate", text)
        typed = self.base / "typed.pdf"
        write_pdf(typed, ["Already has words"])
        _, text = read_contents(typed, "pdf", ".pdf", typed.stat().st_size, fake)
        self.assertNotIn("Northgate", text)                  # PDFs with text aren't read again
        self.assertEqual(len(fake.pictures), 2)

    def test_remembered_scans_are_read_once_recognition_is_available(self):
        from sortzen.scanning.readers import needs_reread

        scan = SimpleNamespace(ext=".pdf", kind="pdf", size=50_000, cloud_only=False, details={"no_text": True})
        self.assertFalse(needs_reread(scan, ocr=False))
        self.assertTrue(needs_reread(scan, ocr=True))
        scan.details["ocr_tried"] = True
        self.assertFalse(needs_reread(scan, ocr=True))
        photo = SimpleNamespace(ext=".jpg", kind="image", size=900_000, cloud_only=False,
                                details={"camera": "Pixelcam PX-9"})
        self.assertFalse(needs_reread(photo, ocr=True))

    @unittest.skipUnless(os.name == "nt", "Windows text recognition needs Windows")
    def test_windows_reads_a_picture_of_text(self):
        from PIL import Image, ImageDraw, ImageFont

        from sortzen.scanning import ocr

        found = ocr.recognizer()
        if found is None:
            self.skipTest(ocr.why_unavailable())
        picture = self.base / "note.png"
        image = Image.new("RGB", (900, 220), "white")
        ImageDraw.Draw(image).text((30, 60), "INVOICE 2024 GARDEN", fill="black", font=ImageFont.load_default(64))
        image.save(picture)
        text = ocr.read_text(found, picture, ".png")
        self.assertIn("INVOICE", text.upper())
