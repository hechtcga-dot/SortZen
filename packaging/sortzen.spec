# PyInstaller build for SortZen.
#   pyinstaller packaging/sortzen.spec --noconfirm
# Output: dist/SortZen/ - the program folder the installer installs. A folder (not one
# self-unpacking exe) starts quickly and is less likely to upset virus scanners.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
from sortzen import __version__  # noqa: E402

datas = [
    (str(ROOT / "packaging" / "README.txt"), "."),
    (str(SRC / "sortzen" / "ui" / "fonts"), "sortzen/ui/fonts"),
    (str(SRC / "sortzen" / "ui" / "assets"), "sortzen/ui/assets"),
    (str(ROOT / "packaging" / "sortzen.ico"), "sortzen/ui/assets"),
]
datas += collect_data_files("google.genai")
datas += collect_data_files("pypdfium2") + collect_data_files("pypdfium2_raw")    # drawing scanned PDF pages
binaries = collect_dynamic_libs("pypdfium2_raw")
MODEL = SRC / "sortzen" / "meaning" / "model"            # packaging/get_meaning_model.py downloads it
if not (MODEL / "model.safetensors").exists():
    raise SystemExit("The meaning model is missing: run python packaging/get_meaning_model.py first")
datas.append((str(MODEL), "sortzen/meaning/model"))
hiddenimports = collect_submodules("google.genai", filter=lambda name: ".tests" not in name) + [
    "PySide6.QtSvg", "keyring.backends.Windows", "win32ctypes.core",
]
if sys.platform.startswith("win"):                  # Windows text recognition
    hiddenimports += collect_submodules("winrt")

# Qt parts SortZen does not use (a smaller program that starts faster).
excludes = [
    "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuick3D",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtTest", "PySide6.QtSql", "PySide6.QtNetworkAuth",
    "PySide6.QtWebSockets", "PySide6.QtHttpServer", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
    "PySide6.QtNetwork", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPrintSupport",
    "matplotlib", "pandas", "IPython", "pytest",
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)

# Qt files nothing uses: the software OpenGL renderer, Qt Quick/QML, PDF, network, translations
# and plugins for other systems. The small SVG icon engine stays, so style-sheet arrows are sharp.
DROP = ("opengl32sw", "qt6quick", "qt6qml", "qt6pdf", "qt6network", "qt6virtualkeyboard",
        "qt6opengl", "d3dcompiler", "/translations/", "/qmltooling/", "/tls/",
        "/networkinformation/", "/platforminputcontexts/", "/generic/",
        "qpdf", "qminimal", "qdirect2d", "qvnc", "qicns", "qtga", "qwbmp")


def keep(entry):
    name = entry[0].replace("\\", "/").lower()
    return not any(d in "/" + name for d in DROP)


a.binaries = [b for b in a.binaries if keep(b)]
a.datas = [d for d in a.datas if keep(d)]
pyz = PYZ(a.pure)

version_file = None
if sys.platform.startswith("win"):
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )
    nums = [int(x) for x in __version__.split(".")[:3] if x.isdigit()] + [0, 0, 0, 0]
    ver = tuple(nums[:4])
    version_file = VSVersionInfo(
        ffi=FixedFileInfo(filevers=ver, prodvers=ver),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "SortZen"),
                StringStruct("FileDescription", "SortZen - sorts messy folders"),
                StringStruct("FileVersion", __version__),
                StringStruct("ProductName", "SortZen"),
                StringStruct("ProductVersion", __version__),
                StringStruct("OriginalFilename", "SortZen.exe"),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SortZen",
          icon=str(ROOT / "packaging" / "sortzen.ico"), version=version_file, console=False, upx=False)
COLLECT(exe, a.binaries, a.datas, name="SortZen", upx=False)
