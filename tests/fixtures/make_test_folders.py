"""Build the synthetic test folders: two messy sources, already-sorted destinations, an answer key.

All names, organisations and contents are made up. The same seed always builds the same files.

    python tests/fixtures/make_test_folders.py OUTPUT_FOLDER [--seed N]

Layout of OUTPUT_FOLDER:
    Downloads/   a browser downloads folder: loose files with real-world names, a messy
                 "older downloads" subfolder (with a project folder inside it), a project
                 folder that belongs together, and an unzipped folder next to its .zip
    Sorted/      destination folders that already hold examples (first-run learning) for
                 Downloads
    My Drive/    a cloud drive tidied in place: loose files (Google link files, copies,
                 typos, scans, odd names) among organised folders that stay where they are
                 and messy folders whose contents are sorted into the organised ones
    answer_key.json

answer_key.json:
    "files":   {"path of a file to sort": "destination folder" or null (belongs in Review)}
    "folders": {"path of a subfolder": outcome}, outcome is "sort inside", "stays",
               "review" or "keep together: <destination folder>"
Paths use "/" and are relative to OUTPUT_FOLDER.

Office files hold only what SortZen reads (text and properties); Office may not open the
presentations. Music, video, installer and shortcut files are short stand-ins with the
right headers. Google link files hold the same small JSON that Google Drive writes.
"""
from __future__ import annotations

import argparse
import calendar
import io
import json
import os
import random
import zipfile
from pathlib import Path

FIXED_DATE = (2026, 1, 1, 0, 0, 0)          # zip entry dates, so every build is identical
EXAMPLE = object()                           # an already-sorted file, not part of the answer key

ME = "Jordan Sample"
KID = "Taylor Sample"
RELATIVE = "Owen Sample"
DIVISION = "Prairie Ridge School Division"
DIV = "PRSD 42"
DIV_DOMAIN = "prsd42.example"
STAFF = ["Dana Whitfield", "Priya Nandal", "Colin Reyes", "Mira Castell"]
APPLICANTS = ["Autumn Ellery", "Ravi Okonkwo", "Lena Marsh", "Theo Brandt", "Sofia Lindqvist", "Ben Achterberg"]
PREVIOUS = "Marcus Feld"
BANK = "Maplestone Bank"
PROPERTY_MANAGER = "Larkspur Property Management"
STORES = ["Fernwood Hardware", "Maple Grocery", "Blue Lake Pharmacy", "Cedar Books", "Harbour Coffee", "Autoparts Depot"]
VENDORS = ["Westline Office Supply", "Prairie Bus Lines", "Northgate Janitorial", "Clearwater Utilities"]
APPS = ["PhotoTidy", "NoteNest", "ZipperPro", "TuneBox", "MapMaker", "BudgetBee"]
SONGS = ["Morning Light", "Long Road", "Paper Boats", "Northern Sky", "Slow River", "City Rain", "Open Fields"]
ARTISTS = ["The Fictionals", "Ada Vale", "North & Pine", "Lumen Choir"]

# Downloads destinations (under Sorted/)
D = {
    "ap": "Sorted/Documents/Work/Accounts Payable",
    "ar": "Sorted/Documents/Work/Accounts Receivable",
    "payroll": "Sorted/Documents/Work/Payroll",
    "audit": "Sorted/Documents/Work/Audit",
    "budget": "Sorted/Documents/Work/Budget",
    "staffing": "Sorted/Documents/Work/Staffing",
    "templates": "Sorted/Documents/Work/Templates",
    "forms": "Sorted/Documents/Work/Forms",
    "projects": "Sorted/Documents/Work/Projects",
    "tax": "Sorted/Documents/Personal/Tax",
    "banking": "Sorted/Documents/Personal/Banking",
    "home": "Sorted/Documents/Personal/Home",
    "career": "Sorted/Documents/Personal/Career",
    "school": "Sorted/Documents/Personal/Kids School",
    "hobbies": "Sorted/Documents/Personal/Hobbies",
    "receipts": "Sorted/Documents/Personal/Receipts",
    "garden": "Sorted/Documents/Side Projects/Garden Planner",
    "camera": "Sorted/Pictures/Camera",
    "screens": "Sorted/Pictures/Screenshots",
    "music": "Sorted/Music",
    "videos": "Sorted/Videos",
    "software": "Sorted/Software/Installers",
    "archives": "Sorted/Archives",
}


# ---------------------------------------------------------------- file writers
def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _core_xml(title: str, author: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
            ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f'<dc:title>{_xml_escape(title)}</dc:title><dc:creator>{_xml_escape(author)}</dc:creator>'
            '</cp:coreProperties>')


def _write_zip(path: Path, files: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(zipfile.ZipInfo(name, FIXED_DATE), content)


def write_docx(path: Path, title: str, author: str, text: str) -> None:
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{_xml_escape(line)}</w:t></w:r></w:p>'
                   for line in text.split("\n"))
    _write_zip(path, {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
            'wordprocessingml.document.main+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.'
            'core-properties+xml"/></Types>'),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/'
            'core-properties" Target="docProps/core.xml"/></Relationships>'),
        "word/document.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body>{body}</w:body></w:document>'),
        "docProps/core.xml": _core_xml(title, author),
    })


def write_xlsx(path: Path, title: str, author: str, rows: list[list[str]]) -> None:
    strings = [cell for row in rows for cell in row]
    shared = "".join(f"<si><t>{_xml_escape(s)}</t></si>" for s in strings)
    cells, n = [], 0
    for r, row in enumerate(rows, start=1):
        row_cells = []
        for c, _ in enumerate(row):
            row_cells.append(f'<c r="{chr(65 + c)}{r}" t="s"><v>{n}</v></c>')
            n += 1
        cells.append(f'<row r="{r}">{"".join(row_cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    _write_zip(path, {
        "xl/sharedStrings.xml": f'<?xml version="1.0" encoding="UTF-8"?><sst {ns}>{shared}</sst>',
        "xl/worksheets/sheet1.xml": f'<?xml version="1.0" encoding="UTF-8"?><worksheet {ns}><sheetData>'
                                    f'{"".join(cells)}</sheetData></worksheet>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8"?><workbook {ns}><sheets>'
                           '<sheet name="Sheet1" sheetId="1"/></sheets></workbook>',
        "docProps/core.xml": _core_xml(title, author),
    })


def write_pptx(path: Path, title: str, author: str, slides: list[list[str]]) -> None:
    files = {"docProps/core.xml": _core_xml(title, author)}
    for i, lines in enumerate(slides, start=1):
        runs = "".join(f"<a:p><a:r><a:t>{_xml_escape(line)}</a:t></a:r></a:p>" for line in lines)
        files[f"ppt/slides/slide{i}.xml"] = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            f'<p:cSld><p:spTree><p:sp><p:txBody>{runs}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
    _write_zip(path, files)


def write_pdf(path: Path, lines: list[str], title: str = "") -> None:
    def escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    text = "BT /F1 11 Tf 50 750 Td 14 TL " + " ".join(f"({escape(line)}) Tj T*" for line in lines) + " ET"
    stream = text.encode("latin-1", "replace")
    info = f"<< /Title ({escape(title)}) >>" if title else "<< >>"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        info.encode("latin-1", "replace"),
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(out.getvalue())


def write_jpeg(path: Path, rng: random.Random, camera: tuple[str, str] | None, taken: str = "") -> None:
    from PIL import Image

    image = Image.new("RGB", (64, 48), tuple(rng.randrange(256) for _ in range(3)))
    exif = Image.Exif()
    if camera:
        exif[0x010F], exif[0x0110] = camera
    if taken:
        exif.get_ifd(0x8769)[0x9003] = taken
    image.save(path, "JPEG", exif=exif.tobytes(), quality=70)


def write_png(path: Path, rng: random.Random) -> None:
    from PIL import Image

    Image.new("RGB", (96, 54), tuple(rng.randrange(256) for _ in range(3))).save(path, "PNG")


def write_google(path: Path, rng: random.Random) -> None:
    doc_id = "".join(rng.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") for _ in range(44))
    kind = {".gdoc": "document", ".gsheet": "spreadsheets", ".gslides": "presentation", ".gform": "forms"}[path.suffix]
    path.write_text(json.dumps({"": "WARNING! DO NOT EDIT THIS FILE! ANY CHANGES MADE WILL BE LOST!",
                                "doc_id": doc_id, "resource_key": "", "email": f"jordan.sample@{DIV_DOMAIN}",
                                "url": f"https://docs.google.com/{kind}/d/{doc_id}/edit"}), encoding="utf-8")


BLOB_HEADERS = {
    ".mp3": b"ID3\x04\x00\x00\x00\x00\x00\x00",
    ".mp4": b"\x00\x00\x00\x18ftypmp42",
    ".exe": b"MZ",
    ".msi": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
    ".lnk": b"L\x00\x00\x00\x01\x14\x02\x00",
    ".kml": b'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2">',
}


# ---------------------------------------------------------------- builder
class Builder:
    def __init__(self, root: Path, seed: int):
        self.root = Path(root)
        self.rng = random.Random(seed)
        self.files: dict[str, str | None] = {}
        self.folders: dict[str, str] = {}

    # one file ----------------------------------------------------------------
    def _target(self, rel: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            stem, ext = os.path.splitext(path.name)
            n = 1
            while path.exists():
                path = path.with_name(f"{stem} ({n}){ext}")
                n += 1
        return path

    def _done(self, path: Path, expect, when) -> str:
        y, m, d = when or (self.rng.choice([2022, 2023, 2024, 2025, 2026]), self.rng.randint(1, 12), self.rng.randint(1, 28))
        stamp = calendar.timegm((y, m, d, self.rng.randint(7, 18), self.rng.randint(0, 59), 0))
        os.utime(path, (stamp, stamp))
        rel = path.relative_to(self.root).as_posix()
        if expect is not EXAMPLE:
            self.files[rel] = expect
        return rel

    def doc(self, rel, text, title="", author=ME, expect=EXAMPLE, when=None):
        path = self._target(rel)
        write_docx(path, title or path.stem, author, text)
        return self._done(path, expect, when)

    def sheet(self, rel, rows, title="", author=ME, expect=EXAMPLE, when=None):
        path = self._target(rel)
        write_xlsx(path, title or path.stem, author, rows)
        return self._done(path, expect, when)

    def slides(self, rel, slides, title="", author=ME, expect=EXAMPLE, when=None):
        path = self._target(rel)
        write_pptx(path, title or path.stem, author, slides)
        return self._done(path, expect, when)

    def pdf(self, rel, lines, title="", expect=EXAMPLE, when=None):
        path = self._target(rel)
        write_pdf(path, lines, title)
        return self._done(path, expect, when)

    def scan(self, rel, expect=EXAMPLE, when=None):
        """A scanned page: a PDF with no typed text."""
        return self.pdf(rel, [], expect=expect, when=when)

    def text(self, rel, text, encoding="utf-8", expect=EXAMPLE, when=None):
        path = self._target(rel)
        path.write_text(text, encoding=encoding)
        return self._done(path, expect, when)

    def csv(self, rel, rows, expect=EXAMPLE, when=None):
        return self.text(rel, "\n".join(",".join(r) for r in rows), expect=expect, when=when)

    def google(self, rel, expect=EXAMPLE, when=None):
        path = self._target(rel)
        write_google(path, self.rng)
        return self._done(path, expect, when)

    def photo(self, rel, camera=("Pixelcam", "PX-9"), expect=EXAMPLE, when=None):
        path = self._target(rel)
        y, m, d = when or (2025, 7, 14)
        write_jpeg(path, self.rng, camera, f"{y}:{m:02d}:{d:02d} {self.rng.randint(8, 20):02d}:{self.rng.randint(0, 59):02d}:00")
        return self._done(path, expect, when)

    def picture(self, rel, expect=EXAMPLE, when=None):
        """An image with no camera details (a screenshot or a saved web image)."""
        path = self._target(rel)
        if path.suffix.lower() == ".png":
            write_png(path, self.rng)
        else:
            write_jpeg(path, self.rng, None)
        return self._done(path, expect, when)

    def archive(self, rel, names, expect=EXAMPLE, when=None):
        path = self._target(rel)
        _write_zip(path, {n: self.rng.randbytes(64) for n in names})
        return self._done(path, expect, when)

    def blob(self, rel, size=2048, expect=EXAMPLE, when=None):
        path = self._target(rel)
        path.write_bytes(BLOB_HEADERS.get(path.suffix.lower(), b"") + self.rng.randbytes(size))
        return self._done(path, expect, when)

    def copy(self, rel, new_rel, expect=EXAMPLE):
        """A duplicate saved again by the browser or Drive, e.g. "name (1).xlsx"."""
        path = self._target(new_rel)
        path.write_bytes((self.root / rel).read_bytes())
        return self._done(path, expect, None)

    def outcome(self, rel, outcome):
        (self.root / rel).mkdir(parents=True, exist_ok=True)
        self.folders[rel] = outcome

    def clock(self) -> str:
        return f"{self.rng.randint(7, 22):02d}{self.rng.randint(0, 59):02d}{self.rng.randint(0, 59):02d}"

    # whole kinds of file, used for bulk ------------------------------------------
    def random_file(self, folder: str, kind: str, expect=EXAMPLE) -> str:
        rng = self.rng
        y, m, d = rng.choice([2022, 2023, 2024, 2025, 2026]), rng.randint(1, 12), rng.randint(1, 28)
        when = (y, m, d)
        if kind == "camera":
            name = rng.choice([f"IMG_{y}{m:02d}{d:02d}_{self.clock()}.jpg", f"IMG_{rng.randint(1000, 9999)}.JPG",
                               f"DSC{rng.randint(10000, 99999)}.JPG"])
            camera = rng.choice([("Pixelcam", "PX-9"), ("Orbit", "Snap 12"), ("Lumina", "LX-2")])
            return self.photo(f"{folder}/{name}", camera, expect, when)
        if kind == "screenshot":
            name = rng.choice([f"Screenshot {y}-{m:02d}-{d:02d} {self.clock()}.png",
                               f"Screenshot_{y}{m:02d}{d:02d}_{self.clock()}.png",
                               f"image ({rng.randint(1, 40)}).png"])
            return self.picture(f"{folder}/{name}", expect, when)
        if kind == "receipt":
            store = rng.choice(STORES)
            name = rng.choice([f"Receipt-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}.pdf",
                               f"Order confirmation {rng.randint(10000, 99999)}.pdf", f"{store} receipt {y}-{m:02d}.pdf"])
            total = f"{rng.randint(5, 300)}.{rng.randint(0, 99):02d}"
            return self.pdf(f"{folder}/{name}", [store, f"Receipt {y}-{m:02d}-{d:02d}", f"Total paid ${total}",
                                                 "Thank you for shopping with us"], expect=expect, when=when)
        if kind == "statement":
            name = rng.choice([f"Statement_{y}-{m:02d}.pdf", f"eStatement {y}{m:02d}.pdf"])
            return self.pdf(f"{folder}/{name}", [BANK, f"Chequing account statement {y}-{m:02d}", f"Account holder: {ME}",
                                                 "Opening balance", "Closing balance"], expect=expect, when=when)
        if kind == "payment_report":
            name = f"Payment Detail Report - {y}{m:02d}{d:02d}{self.clock()}.pdf"
            return self.pdf(f"{folder}/{name}", [DIVISION, "Payment Detail Report", f"EFT batch {rng.randint(100, 999)}",
                                                 f"Vendor: {rng.choice(VENDORS)}", "Approved for payment"],
                            expect=expect, when=when)
        if kind == "invoice":
            vendor = rng.choice(VENDORS)
            name = rng.choice([f"INV{rng.randint(10000, 99999)}.pdf", f"{vendor.split()[0]} invoice {rng.randint(100, 999)}.pdf"])
            return self.pdf(f"{folder}/{name}", [vendor, f"Invoice to {DIVISION}", "Accounts payable", "Net 30"],
                            expect=expect, when=when)
        if kind == "applicant":
            person = rng.choice(APPLICANTS)
            first, last = person.split()
            name = rng.choice([f"{y} {first}_{last}_Resume.pdf", f"{last} {first} - Cover Letter.pdf",
                               f"Resume - {person}.docx"])
            text = [f"{person}", f"Application for Educational Assistant, {DIVISION}",
                    "Experience: classroom support, first aid", "References available on request"]
            if name.endswith(".pdf"):
                return self.pdf(f"{folder}/{name}", text, expect=expect, when=when)
            return self.doc(f"{folder}/{name}", "\n".join(text), author=person, expect=expect, when=when)
        if kind == "installer":
            app = rng.choice(APPS)
            name = rng.choice([f"{app}Setup.exe", f"{app.lower()}-installer-v{rng.randint(1, 9)}.{rng.randint(0, 9)}.msi",
                               f"{app}_x64_setup.exe"])
            return self.blob(f"{folder}/{name}", 3000, expect, when)
        if kind == "music":
            return self.blob(f"{folder}/{rng.choice(ARTISTS)} - {rng.choice(SONGS)}.mp3", 2048, expect, when)
        if kind == "video":
            return self.blob(f"{folder}/VID_{y}{m:02d}{d:02d}_{self.clock()}.mp4", 4096, expect, when)
        if kind == "archive":
            stem = rng.choice(["holiday_photos", "fonts_pack", "wallpapers", "printer_drivers", "sample_music"])
            return self.archive(f"{folder}/{stem}_{rng.randint(1, 99)}.zip", [f"{stem}/item_{i}.dat" for i in range(3)],
                                expect, when)
        if kind == "homework":
            topic = rng.choice(["Water cycle", "Fractions practice", "Solar system", "Book report", "Spelling list"])
            return self.doc(f"{folder}/{topic} - {KID.split()[0]}.docx",
                            f"{topic}\nName: {KID}\nGrade 4\nDue Friday", author=KID, expect=expect, when=when)
        if kind == "garden":
            topic = rng.choice(["feature list", "plant database", "watering schedule logic", "UI sketches notes"])
            return self.doc(f"{folder}/Garden Planner {topic}.docx",
                            f"Garden Planner app\n{topic}\nNext version: seed catalog import", expect=expect, when=when)
        if kind == "unclear":
            choice = rng.randrange(4)
            if choice == 0:
                return self.pdf(f"{folder}/document ({rng.randint(1, 9)}).pdf", ["Page 1"], expect=expect, when=when)
            if choice == 1:
                return self.text(f"{folder}/untitled.txt", "asdf", expect=expect, when=when)
            if choice == 2:
                return self.blob(f"{folder}/download.bin", 512, expect, when)
            return self.scan(f"{folder}/{''.join(rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ0123456789') for _ in range(6))}.PDF",
                             expect, when)
        raise ValueError(kind)


BULK_KINDS = {   # kind -> Downloads destination key (None = Review)
    "camera": "camera", "screenshot": "screens", "receipt": "receipts", "statement": "banking",
    "payment_report": "ap", "invoice": "ap", "applicant": "staffing", "installer": "software",
    "music": "music", "video": "videos", "archive": "archives", "homework": "school", "garden": "garden",
    "unclear": None,
}


# ---------------------------------------------------------------- scenario 1: Downloads
def _sorted_examples(b: Builder) -> None:
    for kind, key in BULK_KINDS.items():
        if key:
            for _ in range(5):
                b.random_file(D[key], kind)
    for i, (topic, rows) in enumerate([
        ("Fee Payments", [["Student", "Fee", "Paid"], ["Grade 7", "Field trip", "Yes"]]),
        ("Fee Payments", [["Student", "Fee", "Paid"], ["Grade 9", "Band", "No"]]),
        ("School fees outstanding", [["School", "Outstanding"], ["Westview", "1240"]]),
    ]):
        b.sheet(f"{D['ar']}/{2022 + i}-{2023 + i} {topic}.xlsx", rows, title=f"{DIV} {topic}")
    for year in (2022, 2023, 2024):
        b.sheet(f"{D['payroll']}/Pay Increase Analysis - {STAFF[year % 4]}.xlsx",
                [["Employee", "Step", "Increase"], [STAFF[year % 4], "4", "2.5%"]], title="Pay increase analysis")
        b.pdf(f"{D['payroll']}/T4 summary {year}.pdf", [DIVISION, f"T4 summary {year}", "Payroll remittance"])
        b.pdf(f"{D['audit']}/{year} TB backup.pdf", [DIVISION, f"Trial balance {year}", "Year-end audit"])
        b.pdf(f"{D['audit']}/{year} ADJ entries.pdf", [DIVISION, f"Adjusting entries {year}", "Audit"])
        b.sheet(f"{D['budget']}/Projected Cash Flow {year}.xlsx", [["Month", "Inflow", "Outflow"], ["Sep", "4.1M", "3.9M"]],
                title=f"{DIV} cash flow")
        b.pdf(f"{D['tax']}/{year} T4 - {ME}.pdf", [f"Statement of remuneration {year}", f"Employee: {ME}",
                                                    f"Employer: {DIVISION}"])
        b.pdf(f"{D['tax']}/{year} Notice of Assessment.pdf", ["Notice of Assessment", f"Tax year {year}", ME])
    b.sheet(f"{D['budget']}/Board of Trustees Expense Sep-Feb 2024.xlsx", [["Trustee", "Mileage"], ["Ward 1", "212"]])
    b.sheet(f"{D['templates']}/2021-2022 Op Costs template.xlsx", [["Account", "Budget", "Actual"], ["Utilities", "", ""]])
    b.doc(f"{D['templates']}/{ME.split()[0][0]}. Sample letterhead.docx", f"{ME}\nSecretary-Treasurer\n{DIVISION}")
    b.doc(f"{D['templates']}/Memo template.docx", f"{DIVISION}\nMemo\nTo:\nFrom:\nRe:")
    for form in ("Mileage claim form", "Purchase requisition", "Expense reimbursement form"):
        b.pdf(f"{D['forms']}/{form}.pdf", [DIVISION, form, "Signature", "Approved by"])
    b.doc(f"{D['staffing']}/Receptionist 0.4 Division Office posting.docx",
          f"{DIVISION}\nJob posting: Receptionist 0.4 FTE\nClosing date: September 15")
    b.doc(f"{D['career']}/{ME} Resume 2022.docx",
          f"{ME}\nSecretary-Treasurer, {DIVISION} (2019 to now)\nCPA\nVolunteer treasurer, community league")
    b.doc(f"{D['career']}/CPA renewal 2024.docx", f"Professional development hours\n{ME}\nCPA membership renewal")
    b.pdf(f"{D['home']}/{PROPERTY_MANAGER} lease 2022.pdf", [PROPERTY_MANAGER, f"Tenant: {ME}", "Lease agreement"])
    b.pdf(f"{D['home']}/Mortgage statement 2024.pdf", [BANK, "Mortgage statement", ME])
    b.pdf(f"{D['home']}/Home insurance renewal.pdf", ["Home insurance renewal", ME, "Policy period"])
    b.doc(f"{D['hobbies']}/Quilt pattern - Maple Leaf.docx", "Maple leaf quilt block\nFabric: red and white\nCutting list")
    b.pdf(f"{D['hobbies']}/Star chart autumn.pdf", ["Autumn star chart", "Telescope eyepiece guide"])
    b.picture(f"{D['hobbies']}/telescope mount.jpg")
    b.sheet(f"{D['garden']}/Garden Planner seed catalog.xlsx", [["Plant", "Days to harvest"], ["Kale", "55"]])
    osprey = f"{D['projects']}/Project Osprey"
    for i in range(1, 5):
        b.doc(f"{osprey}/Meeting minutes/Osprey meeting {i:02d}.docx",
              f"Project Osprey\nMeeting {i}\nBoiler replacement, Westview School")
    b.sheet(f"{osprey}/Osprey budget tracker.xlsx", [["Item", "Cost"], ["Boiler", "95000"]])


def _downloads(b: Builder) -> None:
    dl = "Downloads"
    loose = {"camera": 20, "screenshot": 18, "receipt": 12, "statement": 6, "payment_report": 10, "invoice": 6,
             "applicant": 10, "installer": 8, "music": 6, "video": 4, "archive": 4, "homework": 6, "garden": 4,
             "unclear": 8}
    for kind, count in loose.items():
        for _ in range(count):
            key = BULK_KINDS[kind]
            b.random_file(dl, kind, D[key] if key else None)

    # Real-world names with copies, typos, odd capitals and look-alike content.
    t = b.sheet(f"{dl}/2022-2023 Op Costs template.xlsx", [["Account", "Budget", "Actual"], ["Utilities", "", ""]],
                expect=D["templates"], when=(2024, 5, 2))
    b.copy(t, f"{dl}/2022-2023 Op Costs template (1).xlsx", expect=D["templates"])
    b.csv(f"{dl}/2023-2024 Fee Payments.csv", [["Student", "Fee", "Paid"], ["Grade 8", "Ski trip", "Yes"]],
          expect=D["ar"], when=(2024, 1, 16))
    b.pdf(f"{dl}/2023 T4.pdf", [f"Statement of remuneration 2023", f"Employee: {ME}", f"Employer: {DIVISION}"],
          expect=D["tax"], when=(2024, 4, 2))
    b.pdf(f"{dl}/2023 Autumn_Ellery_Resume.pdf", ["Autumn Ellery", f"Application for Educational Assistant, {DIVISION}"],
          expect=D["staffing"], when=(2023, 9, 11))
    b.pdf(f"{dl}/Autumn ElleryPRSD42 Cover Letter.pdf", ["Dear hiring committee,", f"I am applying to {DIVISION}."],
          expect=D["staffing"], when=(2023, 9, 11))
    b.doc(f"{dl}/{ME} Resume 2025.docx",
          f"{ME}\nSecretary-Treasurer, {DIVISION} (2019 to now)\nLed audit and budget teams at {DIV}",
          expect=D["career"], when=(2025, 3, 3))                       # own resume: personal, despite the work words
    b.pdf(f"{dl}/AUg 2023 ADJ entries backup.pdf", [DIVISION, "Adjusting entries August 2023", "Audit"],
          expect=D["audit"], when=(2023, 8, 16))
    b.pdf(f"{dl}/Aug 2023 TB backupo.pdf", [DIVISION, "Trial balance August 2023", "Year-end audit"],
          expect=D["audit"], when=(2023, 8, 16))
    b.sheet(f"{dl}/Pay Increase Analysis - Mira Castell.xlsx", [["Employee", "Step"], ["Mira Castell", "5"]],
            expect=D["payroll"], when=(2024, 9, 3))
    b.doc(f"{dl}/T4A Issuance Policy February 2024.docx", f"{DIVISION}\nT4A issuance policy\nPayroll",
          expect=D["payroll"], when=(2024, 2, 5))
    b.sheet(f"{dl}/Board of Trustees Expense Sep-Feb 2025.xlsx", [["Trustee", "Mileage"], ["Ward 2", "180"]],
            expect=D["budget"], when=(2025, 4, 15))
    b.sheet(f"{dl}/Projected Cash Flow Dec-Aug 2023.xlsx", [["Month", "Inflow"], ["Dec", "3.8M"]],
            expect=D["budget"], when=(2023, 4, 25))
    b.doc(f"{dl}/Canada Flag Pattern.docx", "Flag quilt block\nFabric: red and white\nCutting list",
          expect=D["hobbies"], when=(2025, 5, 22))
    b.pdf(f"{dl}/Store Checkout Thank You 02 - Car Manuals.pdf", ["Autoparts Depot", "Thank you for your order",
                                                                   "Car manual set", "Total paid $42.10"],
          expect=D["receipts"], when=(2023, 9, 1))
    b.pdf(f"{dl}/{PROPERTY_MANAGER} - expires May 2028.pdf", [PROPERTY_MANAGER, f"Tenant: {ME}", "Lease term to May 2028"],
          expect=D["home"], when=(2023, 10, 23))
    b.doc(f"{dl}/Shopping Idioms.docx", f"English homework\nName: {KID}\nIdioms about shopping",
          author=KID, expect=D["school"], when=(2023, 12, 8))
    b.doc(f"{dl}/Garden Planner Alpha1.0 notes.docx", "Garden Planner app\nAlpha 1.0 test notes\nSeed catalog import",
          expect=D["garden"], when=(2026, 9, 7))
    b.scan(f"{dl}/scan_priya.nandal@{DIV_DOMAIN}_2026-03-25-14-27-17.pdf", expect=None, when=(2026, 3, 25))
    b.scan(f"{dl}/1DXPB0.PDF", expect=None, when=(2024, 3, 20))
    b.sheet(f"{dl}/Social Club $50 gift card monthly draw.xlsx", [["Month", "Winner"], ["June", "Colin"]],
            expect=None, when=(2026, 6, 4))
    b.picture(f"{dl}/telescope.jpg", expect=None, when=(2025, 8, 20))
    b.blob(f"{dl}/Payroll.lnk", 64, expect=None, when=(2022, 10, 5))

    # A messy folder of old downloads, with a project folder inside it.
    old = f"{dl}/older downloads"
    b.outcome(old, "sort inside")
    for kind in BULK_KINDS:
        for _ in range(12 if kind != "unclear" else 6):
            key = BULK_KINDS[kind]
            b.random_file(old, kind, D[key] if key else None)
    bid = f"{old}/Kestrel bid docs"
    b.outcome(bid, f"keep together: {D['projects']}")
    for name in ("Kestrel bid summary", "Kestrel bid evaluation", "Kestrel bidder questions"):
        b.doc(f"{bid}/{name}.docx", f"Project Kestrel\n{name}\nGymnasium roof replacement tender", when=(2024, 2, 10))
    b.sheet(f"{bid}/Kestrel bid scoring.xlsx", [["Bidder", "Score"], ["Bidder A", "82"]], when=(2024, 2, 12))

    # A project folder that belongs together, with its own subfolders.
    project = f"{dl}/Project Kestrel"
    b.outcome(project, f"keep together: {D['projects']}")
    for i in range(1, 9):
        b.doc(f"{project}/Meeting minutes/Kestrel meeting {i:02d}.docx",
              f"Project Kestrel\nMeeting {i}\nGymnasium roof replacement\nAttendees: {', '.join(STAFF[:2])}",
              when=(2024, 3, i))
    for i in range(1, 7):
        b.pdf(f"{project}/Drawings/Kestrel roof drawing R{i}.pdf", ["Project Kestrel", f"Roof drawing revision {i}"],
              when=(2024, 4, i))
    b.sheet(f"{project}/Kestrel budget tracker.xlsx", [["Item", "Cost"], ["Roofing", "410000"]], when=(2024, 4, 20))
    b.slides(f"{project}/Project Kestrel board update.pptx", [["Project Kestrel"], ["Schedule", "Budget"]],
             when=(2024, 5, 1))

    # An unzipped download next to its zip.
    unzipped = f"{dl}/SD4410B"
    b.outcome(unzipped, f"keep together: {D['forms']}")
    names = [f"SD4410B/Form SD4410B part {i}.pdf" for i in range(1, 5)]
    for name in names:
        b.pdf(f"{dl}/{name}", ["Provincial form SD4410B", "Student data return"], when=(2023, 7, 5))
    b.archive(f"{dl}/SD4410B.ZIP", names, expect=None, when=(2023, 7, 5))


# ---------------------------------------------------------------- scenario 2: My Drive
def _my_drive(b: Builder) -> None:
    md = "My Drive"
    folders = {   # organised folders that stay where they are, with the files already in them
        "2022 Audit": lambda f: [b.pdf(f"{f}/2022 TB backup.pdf", [DIVISION, "Trial balance 2022", "Audit"]),
                                 b.pdf(f"{f}/2022 ADJ entries.pdf", [DIVISION, "Adjusting entries 2022", "Audit"]),
                                 b.sheet(f"{f}/2022 audit PBC list.xlsx", [["Item", "Status"], ["Bank recs", "Done"]])],
        "Accounts Payable": lambda f: [b.random_file(f, "payment_report") for _ in range(4)]
                                      + [b.random_file(f, "invoice") for _ in range(3)],
        "Budget & Cash Flow": lambda f: [b.sheet(f"{f}/Projected Cash Flow 2022.xlsx", [["Month", "Inflow"], ["Sep", "4M"]]),
                                         b.sheet(f"{f}/Board of Trustees Expense Sep-Feb 2024.xlsx",
                                                 [["Trustee", "Mileage"], ["Ward 1", "212"]])],
        "Engagement Templates": lambda f: [b.sheet(f"{f}/2021-2022 Op Costs template.xlsx", [["Account", "Budget"]]),
                                           b.doc(f"{f}/Engagement letter template.docx", f"{DIVISION}\nEngagement letter")],
        "Forms": lambda f: [b.google(f"{f}/Mileage claim.gform"), b.google(f"{f}/Field trip consent.gform"),
                            b.google(f"{f}/Staff survey responses.gsheet")],
        "Payroll backup": lambda f: [b.sheet(f"{f}/Pay Increase Analysis - Colin Reyes.xlsx", [["Employee"], ["Colin Reyes"]]),
                                     b.pdf(f"{f}/T4 summary 2022.pdf", [DIVISION, "T4 summary 2022", "Payroll"])],
        "Staffing": lambda f: [b.random_file(f, "applicant") for _ in range(4)]
                              + [b.doc(f"{f}/Support staff posting.docx", f"{DIVISION}\nSupport staff posting")],
        f"{ME.split()[0]} Personal": lambda f: [
            b.pdf(f"{f}/2022 T4.pdf", ["Statement of remuneration 2022", f"Employee: {ME}"]),
            b.doc(f"{f}/Quilt pattern - Maple Leaf.docx", "Maple leaf quilt block\nCutting list"),
            b.doc(f"{f}/Kids School/Water cycle - Taylor.docx", f"Water cycle\nName: {KID}", author=KID),
            b.google(f"{f}/Kids School/Plant cells explained.gsheet")],
        "Maplestone Bank": lambda f: [b.random_file(f, "statement") for _ in range(3)],
        "mortgage docs": lambda f: [b.pdf(f"{f}/Mortgage statement 2025.pdf", [BANK, "Mortgage statement", ME])],
        "Elmhurst Property": lambda f: [b.pdf(f"{f}/{PROPERTY_MANAGER} lease 2022.pdf",
                                              [PROPERTY_MANAGER, "Elmhurst Property", "Lease agreement"])],
        RELATIVE: lambda f: [b.pdf(f"{f}/{RELATIVE} passport renewal.pdf", ["Passport renewal", RELATIVE])],
        "AI Prompts": lambda f: [b.google(f"{f}/Prompt - meeting summary.gdoc"), b.google(f"{f}/Prompt - budget memo.gdoc")],
        "Cheque Run Clandar": lambda f: [b.sheet(f"{f}/Cheque run calendar 2023.xlsx", [["Date", "Run"], ["Sep 8", "EFT"]])],
        "Grant Reconciliation": lambda f: [b.sheet(f"{f}/Grant rec 2023.xlsx", [["Grant", "Balance"], ["Literacy", "0"]])],
        "KVM Pricing": lambda f: [b.pdf(f"{f}/KVM quote.pdf", ["KVM switch quote", "Westline Office Supply"])],
        "Transition Notes": lambda f: [b.doc(f"{f}/Transition notes {PREVIOUS}.docx", f"Handover from {PREVIOUS}")],
        "rADIO sCHEDULE pROJECT": lambda f: [b.doc(f"{f}/Radio schedule draft.docx", "Radio schedule project\nWeek 1")],
        "Map Projects": lambda f: [b.blob(f"{f}/Bus routes north.kml", 256), b.blob(f"{f}/Bus routes south.kml", 256)],
        f"{PREVIOUS.split()[0]}'s Drive - Sorted": lambda f: [b.doc(f"{f}/Finance/AP procedures.docx", "AP procedures"),
                                                              b.doc(f"{f}/HR/Onboarding checklist.docx", "Onboarding")],
    }
    for name, fill in folders.items():
        b.outcome(f"{md}/{name}", "stays")
        fill(f"{md}/{name}")
    dest = {k: f"{md}/{k}" for k in folders}
    personal = f"{md}/{ME.split()[0]} Personal"

    # Loose files.
    b.google(f"{md}/2023-2024 Fee Payments.gsheet", expect=None)              # no receivables folder here
    t = b.sheet(f"{md}/2022-2023 Op Costs template.xlsx", [["Account", "Budget"]], expect=dest["Engagement Templates"])
    b.copy(t, f"{md}/2022-2023 Op Costs template (1).xlsx", expect=dest["Engagement Templates"])
    b.pdf(f"{md}/2023 T4.pdf", ["Statement of remuneration 2023", f"Employee: {ME}"], expect=personal)
    b.pdf(f"{md}/2023 Autumn_Ellery_Resume.pdf", ["Autumn Ellery", f"Application, {DIVISION}"], expect=dest["Staffing"])
    b.pdf(f"{md}/Autumn ElleryPRSD42 Cover Letter.pdf", [f"I am applying to {DIVISION}."], expect=dest["Staffing"])
    b.google(f"{md}/Accoutns Payable e-mail Preference.gform", expect=dest["Forms"])
    for i in ("", " (1)", " (2)", " (3)"):
        b.google(f"{md}/Blank Quiz{i}.gform", expect=dest["Forms"])
    b.google(f"{md}/RSVP.gform", expect=dest["Forms"])
    b.google(f"{md}/RSVP (1).gform", expect=dest["Forms"])
    b.pdf(f"{md}/AUg 2023 ADJ entries backup.pdf", [DIVISION, "Adjusting entries August 2023"], expect=None)  # 2023, no folder
    b.pdf(f"{md}/Aug 2023 TB backupo.pdf", [DIVISION, "Trial balance August 2023"], expect=None)
    b.google(f"{md}/Garden Planner Alpha1.0.gdoc", expect=None)               # side project with no folder yet
    b.google(f"{md}/Seed Catalog Image Batch Processing.gdoc", expect=None)
    b.google(f"{md}/Seed_Catalog_Final.gsheet", expect=None)
    b.sheet(f"{md}/Board of Trustees Expense Sep-Feb 2025.xlsx", [["Trustee", "Mileage"]], expect=dest["Budget & Cash Flow"])
    b.sheet(f"{md}/Projected Cash Flow Dec-Aug 2023.xlsx", [["Month", "Inflow"]], expect=dest["Budget & Cash Flow"])
    b.sheet(f"{md}/Proposed GL Format - WIP.xlsx", [["Account", "Description"]], expect=None)
    b.doc(f"{md}/Canada Flag Pattern.docx", "Flag quilt block\nCutting list", expect=personal)
    b.google(f"{md}/Overview of Human Digestive System.gsheet", expect=f"{personal}/Kids School")
    b.google(f"{md}/Solstices Versus Equinoxes Explained.gsheet", expect=f"{personal}/Kids School")
    b.sheet(f"{md}/Pay Increase Analysis - Dana Whitfield.xlsx", [["Employee"], ["Dana Whitfield"]],
            expect=dest["Payroll backup"])
    b.doc(f"{md}/T4A Issuance Policy February 2024.docx", f"{DIVISION}\nT4A issuance policy\nPayroll",
          expect=dest["Payroll backup"])
    for _ in range(2):
        b.random_file(md, "payment_report", dest["Accounts Payable"])
    b.blob(f"{md}/Payroll.lnk", 64, expect=None)
    b.pdf(f"{md}/{PROPERTY_MANAGER} - expires May 2028.pdf", [PROPERTY_MANAGER, "Elmhurst Property", "Lease to May 2028"],
          expect=dest["Elmhurst Property"])
    b.pdf(f"{md}/{PROPERTY_MANAGER}.pdf", [PROPERTY_MANAGER, "Elmhurst Property", "Rent schedule"],
          expect=dest["Elmhurst Property"])
    b.doc(f"{md}/Receptionist 0.4 Division Office #1.docx", f"{DIVISION}\nJob posting: Receptionist 0.4 FTE",
          expect=dest["Staffing"])
    b.google(f"{md}/RSVP responses.gsheet", expect=dest["Forms"])
    b.scan(f"{md}/scan_priya.nandal@{DIV_DOMAIN}_2026-03-25-14-27-17.pdf", expect=None)
    b.picture(f"{md}/Screenshot 2024-02-22 141349.png", expect=None)           # no screenshots folder here
    b.archive(f"{md}/SD4410B.ZIP", [f"SD4410B/Form SD4410B part {i}.pdf" for i in range(1, 3)], expect=None)
    b.outcome(f"{md}/SD4410B", "stays")
    b.pdf(f"{md}/SD4410B/Form SD4410B part 1.pdf", ["Provincial form SD4410B"])
    b.pdf(f"{md}/Store Checkout Thank You 02 - Car Manuals.pdf", ["Autoparts Depot", "Total paid $42.10"], expect=personal)
    b.doc(f"{md}/Prairie Co-op Card Signup - DRAFT.docx", f"Prairie Co-op membership\nName: {ME}", expect=personal)
    b.doc(f"{md}/{ME.split()[0][0]}. Sample letterhead (2).docx", f"{ME}\n{DIVISION}", expect=dest["Engagement Templates"])
    b.google(f"{md}/Untitled document.gdoc", expect=None)
    b.picture(f"{md}/telescope.jpg", expect=personal)
    b.doc(f"{md}/Mortgage renewal offer 2026.docx", f"{BANK}\nMortgage renewal offer\n{ME}", expect=dest["mortgage docs"])

    # Messy folders: their files belong in the organised folders above.
    backup = f"{md}/{ME.split()[0]}'s OneDrive backup"
    b.outcome(backup, "sort inside")
    for _ in range(3):
        b.random_file(backup, "statement", dest["Maplestone Bank"])
        b.random_file(backup, "applicant", dest["Staffing"])
        b.random_file(backup, "payment_report", dest["Accounts Payable"])
    b.doc(f"{backup}/Water cycle quiz - Taylor.docx", f"Water cycle quiz\nName: {KID}", author=KID,
          expect=f"{personal}/Kids School")
    b.google(f"{backup}/Prompt - staff newsletter.gdoc", expect=dest["AI Prompts"])
    unsorted = f"{md}/{PREVIOUS.split()[0]}'s Drive - Unsorted"
    b.outcome(unsorted, "sort inside")
    for _ in range(4):
        b.random_file(unsorted, "invoice", dest["Accounts Payable"])
    b.sheet(f"{unsorted}/Grant rec 2021.xlsx", [["Grant", "Balance"], ["Literacy", "120"]], expect=dest["Grant Reconciliation"])
    b.doc(f"{unsorted}/Onboarding checklist v2.docx", "Onboarding\nNew staff checklist", expect=None)

    b.outcome(f"{md}/To e-mail", "review")                    # a holding folder kept on purpose, or clutter
    b.doc(f"{md}/To e-mail/Letter to auditors.docx", f"{DIVISION}\nLetter to auditors", expect=None)
    b.pdf(f"{md}/To e-mail/Signed contract.pdf", ["Signed contract", "Westline Office Supply"], expect=None)
    restored = f"{md}/{PREVIOUS.lower().replace(' ', '.')} - Restored on 04-Oct-2022 15 01 27"
    b.outcome(restored, "review")                             # a former colleague's whole drive
    b.doc(f"{restored}/Budget notes.docx", "Budget notes 2021", expect=None)
    b.doc(f"{restored}/Personal/Vacation request.docx", f"Vacation request\n{PREVIOUS}", expect=None)


def build(output: Path, seed: int = 7) -> Path:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    b = Builder(output, seed)
    _sorted_examples(b)
    _downloads(b)
    _my_drive(b)
    # Files inside a folder with an outcome other than "sort inside" are not sorted one by one.
    held = [rel for rel, outcome in b.folders.items() if outcome != "sort inside"]
    files = {rel: dest for rel, dest in b.files.items()
             if not any(rel.startswith(folder + "/") for folder in held)}
    key = {"files": dict(sorted(files.items())), "folders": dict(sorted(b.folders.items()))}
    (output / "answer_key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("output")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    out = build(Path(args.output), args.seed)
    key = json.loads((out / "answer_key.json").read_text(encoding="utf-8"))
    print(f"Built test folders in {out}: {len(key['files'])} files and {len(key['folders'])} subfolders to sort")


if __name__ == "__main__":
    main()
