"""Run SortZen from source: ``python packaging/launcher.py``. Also the packaged program's entry point."""
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sortzen.ui.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
