"""Build the synthetic test folders: a messy Downloads, already-sorted destinations, an answer key.

All names, companies and contents are made up. The same seed always builds the same files.

    python tests/fixtures/make_test_folders.py OUTPUT_FOLDER [--seed N]

Layout of OUTPUT_FOLDER:
    Downloads/          about 300 mixed files to sort
    Sorted/             destination folders that already hold examples (first-run learning)
    answer_key.json     {"Downloads file name": "destination folder relative to Sorted" or null}

Office files hold only what SortZen reads (text and properties); Office may not open the
presentations. Music, video and installer files are short stand-ins with the right headers.
"""
from __future__ import annotations

import argparse
import io
import json
import random
import zipfile
from pathlib import Path

WORK_COMPANY = "Example Co."
FIXED_DATE = (2026, 1, 1, 0, 0, 0)          # zip entry dates, so every build is identical
WORK_TOPICS = [
    "quarterly sales review", "warehouse schedule", "client onboarding", "safety audit", "budget forecast",
    "shipping rates", "team meeting notes", "vendor contract", "inventory count", "project timeline",
    "hiring plan", "customer survey results",
]
WORK_PEOPLE = ["Avery Lane", "Morgan Pike", "Casey Hollow", "Riley Stone", "Jamie Brook"]
PERSONAL_DOCS = [
    ("Resume - Jordan Sample", "Jordan Sample\nExperience\nOperations Coordinator, {company} (2021 to now)\n"
                               "Planned shipping schedules and trained new staff.\nEducation\nDiploma in Business"),
    ("Cover letter", "Dear hiring manager,\nI am applying for the coordinator role. At {company} I lead a team of "
                     "four.\nKind regards,\nJordan Sample"),
    ("Banana bread recipe", "Ingredients: 3 ripe bananas, 2 cups flour, 1 cup sugar, 2 eggs.\nBake at 350F for "
                            "60 minutes."),
    ("Letter to landlord", "Dear Ms. Fieldstone,\nThe kitchen tap is leaking again. Could someone take a look "
                           "this week?\nThanks, Jordan"),
    ("Trip plan Banff", "Day 1 drive and check in. Day 2 Lake Louise hike. Day 3 hot springs and dinner."),
    ("Wedding speech", "For Sam and Alex: thank you all for coming tonight. I've known Sam since grade school."),
    ("Kids school forms", "Field trip permission form. Student: Taylor Sample. Grade 4. Emergency contact: Jordan."),
]
STORES = ["Fernwood Hardware", "Maple Grocery", "Blue Lake Pharmacy", "Cedar Books", "Harbour Coffee"]
PRODUCTS = ["Kettle KX200", "Robot Vacuum RV-7", "Desk Lamp L3", "Garden Hose Reel", "Air Fryer AF5"]
SONGS = ["Morning Light", "Long Road", "Paper Boats", "Northern Sky", "Slow River", "City Rain", "Open Fields"]
ARTISTS = ["The Fictionals", "Ada Vale", "North & Pine", "Lumen Choir"]
APPS = ["PhotoTidy", "NoteNest", "ZipperPro", "TuneBox", "MapMaker", "BudgetBee"]

# kind -> (destination under Sorted, how many in Downloads, how many already sorted)
PLAN = {
    "work_doc": ("Documents/Word/Work", 30, 12),
    "personal_doc": ("Documents/Word/Personal", 20, 8),
    "receipt": ("Documents/PDF/Receipts", 25, 8),
    "manual": ("Documents/PDF/Manuals", 10, 4),
    "work_sheet": ("Documents/Spreadsheets/Work", 15, 5),
    "budget_sheet": ("Documents/Spreadsheets/Budget", 10, 4),
    "work_slides": ("Documents/Presentations/Work", 10, 4),
    "note": ("Documents/Notes", 20, 6),
    "camera": ("Pictures/Camera", 50, 15),
    "screenshot": ("Pictures/Screenshots", 35, 10),
    "music": ("Music", 20, 8),
    "video": ("Videos", 12, 4),
    "installer": ("Software/Installers", 15, 5),
    "archive": ("Archives", 15, 4),
    "unclear": (None, 13, 0),
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


def write_docx(path: Path, title: str, author: str, text: str) -> None:
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{_xml_escape(line)}</w:t></w:r></w:p>'
                   for line in text.split("\n"))
    files = {
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
    }
    _write_zip(path, files)


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
    files = {
        "xl/sharedStrings.xml": f'<?xml version="1.0" encoding="UTF-8"?><sst {ns}>{shared}</sst>',
        "xl/worksheets/sheet1.xml": f'<?xml version="1.0" encoding="UTF-8"?><worksheet {ns}><sheetData>'
                                    f'{"".join(cells)}</sheetData></worksheet>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8"?><workbook {ns}><sheets>'
                           '<sheet name="Sheet1" sheetId="1"/></sheets></workbook>',
        "docProps/core.xml": _core_xml(title, author),
    }
    _write_zip(path, files)


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


def _write_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(zipfile.ZipInfo(name, FIXED_DATE), content)


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


# ---------------------------------------------------------------- one file of each kind
class Builder:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.used: set[str] = set()

    def unique(self, name: str) -> str:
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        candidate, n = name, 2
        while candidate.lower() in self.used:
            candidate = f"{stem} ({n}).{ext}" if ext else f"{stem} ({n})"
            n += 1
        self.used.add(candidate.lower())
        return candidate

    def date(self) -> tuple[int, int, int]:
        return self.rng.choice([2024, 2025, 2026]), self.rng.randint(1, 12), self.rng.randint(1, 28)

    def make(self, kind: str, folder: Path) -> str:
        rng = self.rng
        y, m, d = self.date()
        if kind == "work_doc":
            topic = rng.choice(WORK_TOPICS)
            name = self.unique(f"{topic.title()} {y}-{m:02d}.docx")
            author = rng.choice(WORK_PEOPLE)
            write_docx(folder / name, f"{WORK_COMPANY} {topic}", author,
                       f"{WORK_COMPANY} - {topic}\nPrepared by {author}\nThis document covers the {topic} for "
                       f"{WORK_COMPANY} warehouse operations in {y}.\nAction items are due by the end of month {m}.")
        elif kind == "personal_doc":
            title, text = rng.choice(PERSONAL_DOCS)
            name = self.unique(f"{title}.docx")
            write_docx(folder / name, title, "Jordan Sample", text.format(company=WORK_COMPANY))
        elif kind == "receipt":
            store = rng.choice(STORES)
            name = self.unique(rng.choice([f"Receipt {store} {y}-{m:02d}-{d:02d}.pdf", f"receipt_{rng.randint(1000, 9999)}.pdf",
                                           f"order-confirmation-{rng.randint(10000, 99999)}.pdf"]))
            total = f"{rng.randint(5, 300)}.{rng.randint(0, 99):02d}"
            write_pdf(folder / name, [store, f"Receipt  {y}-{m:02d}-{d:02d}", f"Subtotal {total}", "GST 5%",
                                      f"Total paid ${total}", "Thank you for shopping with us"], title=f"{store} receipt")
        elif kind == "manual":
            product = rng.choice(PRODUCTS)
            name = self.unique(rng.choice([f"{product} manual.pdf", f"{product.split()[0]}_user_guide.pdf"]))
            write_pdf(folder / name, [f"{product} User Manual", "Safety instructions", "Getting started",
                                      "Cleaning and care", "Warranty: one year from date of purchase"],
                      title=f"{product} manual")
        elif kind == "work_sheet":
            topic = rng.choice(["Sales", "Inventory", "Shipping log", "Timesheet"])
            name = self.unique(f"{WORK_COMPANY} {topic} Q{rng.randint(1, 4)} {y}.xlsx")
            write_xlsx(folder / name, f"{WORK_COMPANY} {topic}", rng.choice(WORK_PEOPLE),
                       [["Region", "Units", "Customer"], ["West", str(rng.randint(10, 900)), f"{WORK_COMPANY} client"],
                        ["North", str(rng.randint(10, 900)), "Warehouse 3"]])
        elif kind == "budget_sheet":
            name = self.unique(rng.choice([f"Household budget {y}.xlsx", f"Monthly expenses {y}-{m:02d}.xlsx"]))
            write_xlsx(folder / name, "Household budget", "Jordan Sample",
                       [["Item", "Amount"], ["Rent", "1650"], ["Groceries", str(rng.randint(400, 900))],
                        ["Car insurance", "140"], ["Savings", "300"]])
        elif kind == "work_slides":
            topic = rng.choice(WORK_TOPICS)
            name = self.unique(f"{WORK_COMPANY} {topic}.pptx")
            write_pptx(folder / name, f"{WORK_COMPANY} {topic}", rng.choice(WORK_PEOPLE),
                       [[f"{WORK_COMPANY}", topic.title()], ["Goals", "Timeline", "Owners"], ["Next steps"]])
        elif kind == "note":
            title, text = rng.choice([
                ("shopping list", "milk\neggs\nbread\ncoffee filters\nbatteries AA"),
                ("ideas", "paint the fence\nfix bike brakes\nbook dentist"),
                ("wifi password for guests", "Network: SampleHome\nAsk Jordan for the password"),
                ("gift ideas", "Mom: garden gloves\nSam: board game\nAlex: coffee mug"),
                ("packing list", "passport\ncharger\nsunscreen\nhiking boots"),
            ])
            name = self.unique(f"{title}.txt")
            (folder / name).write_text(text, encoding=rng.choice(["utf-8", "utf-16", "cp1252"]))
        elif kind == "camera":
            name = self.unique(f"IMG_{rng.randint(1000, 9999)}.JPG")
            camera = rng.choice([("Pixelcam", "PX-9"), ("Orbit", "Snap 12"), ("Lumix-ish", "LX-2")])
            write_jpeg(folder / name, rng, camera, f"{y}:{m:02d}:{d:02d} {rng.randint(8, 20):02d}:{rng.randint(0, 59):02d}:00")
        elif kind == "screenshot":
            name = self.unique(rng.choice([
                f"Screenshot {y}-{m:02d}-{d:02d} {rng.randint(80000, 235959):06d}.png",
                f"Screenshot_{y}{m:02d}{d:02d}_{rng.randint(100000, 235959)}.png",
                f"Capture{rng.randint(1, 40)}.PNG"]))
            write_png(folder / name, rng)
        elif kind == "music":
            name = self.unique(f"{rng.choice(ARTISTS)} - {rng.choice(SONGS)}.mp3")
            (folder / name).write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00" + rng.randbytes(2048))
        elif kind == "video":
            name = self.unique(f"VID_{y}{m:02d}{d:02d}_{rng.randint(100000, 235959)}.mp4")
            (folder / name).write_bytes(b"\x00\x00\x00\x18ftypmp42" + rng.randbytes(4096))
        elif kind == "installer":
            app = rng.choice(APPS)
            name = self.unique(rng.choice([f"{app}Setup.exe", f"{app.lower()}-installer-v{rng.randint(1, 9)}.{rng.randint(0, 9)}.msi",
                                           f"{app}_x64_setup.exe"]))
            header = b"MZ" if name.endswith(".exe") else b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
            (folder / name).write_bytes(header + rng.randbytes(3000))
        elif kind == "archive":
            stem = rng.choice(["holiday_photos", "project_files", "fonts_pack", "tax_documents", "wallpapers"])
            name = self.unique(f"{stem}_{rng.randint(1, 99)}.zip")
            with zipfile.ZipFile(folder / name, "w") as archive:
                for i in range(rng.randint(2, 6)):
                    archive.writestr(zipfile.ZipInfo(f"{stem}/item_{i}.dat", FIXED_DATE), rng.randbytes(64))
        elif kind == "unclear":
            choice = rng.randrange(4)
            if choice == 0:
                name = self.unique("document.pdf")
                write_pdf(folder / name, ["Page 1"])
            elif choice == 1:
                name = self.unique("untitled.txt")
                (folder / name).write_text("asdf", encoding="utf-8")
            elif choice == 2:
                name = self.unique("download.bin")
                (folder / name).write_bytes(rng.randbytes(512))
            else:
                name = self.unique("file")
                (folder / name).write_bytes(rng.randbytes(256))
        else:
            raise ValueError(kind)
        return name


def build(output: Path, seed: int = 7) -> Path:
    output = Path(output)
    downloads, sorted_root = output / "Downloads", output / "Sorted"
    downloads.mkdir(parents=True, exist_ok=True)
    builder = Builder(seed)
    answer_key: dict[str, str | None] = {}
    for kind, (destination, in_downloads, already_sorted) in PLAN.items():
        if destination:
            folder = sorted_root / destination
            folder.mkdir(parents=True, exist_ok=True)
            for _ in range(already_sorted):
                builder.make(kind, folder)
        for _ in range(in_downloads):
            answer_key[builder.make(kind, downloads)] = destination
    (output / "answer_key.json").write_text(json.dumps(dict(sorted(answer_key.items())), indent=2), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("output")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    out = build(Path(args.output), args.seed)
    print(f"Built test folders in {out}")


if __name__ == "__main__":
    main()
