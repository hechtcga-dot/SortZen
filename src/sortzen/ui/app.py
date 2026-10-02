"""Start the SortZen desktop program."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler


def _setup_logging(logs_dir):
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(logs_dir / "sortzen.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger("sortzen")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    for noisy in ("google_genai", "google.genai", "httpx"):
        logging.getLogger(noisy).setLevel(logging.ERROR)


def create_app(argv=None):
    from PySide6.QtWidgets import QApplication

    from . import theme
    from .icons import app_icon

    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("SortZen")
    app.setOrganizationName("SortZen")
    app.setStyle("Fusion")
    theme.load_fonts()
    app.setFont(theme.font(9.5))
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.STYLE)
    app.setWindowIcon(app_icon())
    return app


def self_test(report_path: str) -> int:
    """``SortZen.exe --self-test=report.json``: start, check the bundled pieces, exit.

    The Windows build runs this to prove the packaged program works before publishing it.
    """
    import json
    import os
    import tempfile
    import traceback

    os.environ["SORTZEN_DATA_DIR"] = tempfile.mkdtemp(prefix="sortzen_selftest_")
    checks = {}
    try:
        argv = [sys.argv[0]] if os.getenv("QT_QPA_PLATFORM") else [sys.argv[0], "-platform", "offscreen"]
        app = create_app(argv)
        from PySide6.QtGui import QFontDatabase

        from ..services import AppService
        from .main_window import MainWindow

        families = set(QFontDatabase.families())
        checks["fonts"] = all(f in families for f in ("Fraunces", "IBM Plex Sans", "IBM Plex Mono"))
        from google import genai
        import keyring  # noqa: F401
        import pypdf  # noqa: F401
        from PIL import Image  # noqa: F401

        genai.Client(api_key="self-test")          # the AI library loads (no network call)
        checks["libraries"] = True
        window = MainWindow(AppService())
        window.show()
        app.processEvents()
        checks["window"] = window.tabs.count() >= 1
        window.close()
    except Exception:
        checks["error"] = traceback.format_exc()
    ok = bool(checks) and all(v is True for v in checks.values())
    checks["ok"] = ok
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(checks, f, indent=2)
    except OSError:
        pass
    return 0 if ok else 1


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    for arg in argv[1:]:
        if arg.startswith("--self-test"):
            return self_test(arg.partition("=")[2] or "sortzen_self_test.json")
    if sys.platform.startswith("win"):
        try:  # own taskbar icon instead of Python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SortZen.SortZen.0")
        except Exception:
            pass
    app = create_app(argv)

    from ..config import default_paths
    from ..services import AppService
    from .main_window import MainWindow

    paths = default_paths()
    _setup_logging(paths.logs_dir)
    log = logging.getLogger("sortzen")

    def excepthook(exc_type, exc, tb):
        log.error("Unhandled error", exc_info=(exc_type, exc, tb))
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Something went wrong", f"{exc}\n\nDetails were written to the activity log.")

    sys.excepthook = excepthook
    window = MainWindow(AppService(paths))
    window.showMaximized()
    return app.exec()
