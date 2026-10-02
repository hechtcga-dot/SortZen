import re
import unittest

from sortzen import __version__
from sortzen.config import APP_VERSION


class VersionTest(unittest.TestCase):
    def test_version_format(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_shown_version_is_major_minor(self):
        self.assertEqual(APP_VERSION, ".".join(__version__.split(".")[:2]))
        self.assertTrue(re.fullmatch(r"\d+\.\d+", APP_VERSION))
