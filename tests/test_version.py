import re
import unittest
from pathlib import Path

from sortzen import __version__
from sortzen.config import APP_VERSION

PACKAGING = Path(__file__).resolve().parent.parent / "packaging"


class VersionTest(unittest.TestCase):
    def test_version_format(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_shown_version_is_major_minor(self):
        self.assertEqual(APP_VERSION, ".".join(__version__.split(".")[:2]))
        self.assertTrue(re.fullmatch(r"\d+\.\d+", APP_VERSION))

    def test_installer_and_readme_agree(self):
        iss = (PACKAGING / "sortzen.iss").read_text(encoding="utf-8")
        self.assertIn(f'#define AppVersion "{__version__}"', iss)
        readme = (PACKAGING / "README.txt").read_text(encoding="utf-8")
        self.assertTrue(readme.startswith(f"SortZen {APP_VERSION} - README"))
        self.assertIn(f"SortZen-Setup-{__version__}.exe", readme)
        self.assertIn(f"What's new in {APP_VERSION}", readme)
