import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sortzen.repositories.api_keys import ApiKeyStore, KeyStorageError
from sortzen.repositories.settings import SettingsRepository


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, name):
        return self.store.get((service, name))

    def set_password(self, service, name, value):
        self.store[(service, name)] = value

    def delete_password(self, service, name):
        del self.store[(service, name)]


class BrokenKeyring(FakeKeyring):
    def set_password(self, service, name, value):
        raise RuntimeError("no backend")


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "settings.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_round_trip(self):
        SettingsRepository(self.path).set("ai_service", "claude")
        self.assertEqual(SettingsRepository(self.path).get("ai_service"), "claude")
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_damaged_file_reads_as_empty(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(SettingsRepository(self.path).data, {})
        self.path.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(SettingsRepository(self.path).data, {})


class ApiKeyStoreTest(unittest.TestCase):
    def test_save_load_clear(self):
        store = ApiKeyStore(FakeKeyring())
        store.save("gemini", "  abc123  ")
        self.assertEqual(store.load("gemini"), "abc123")
        store.clear("gemini")
        self.assertEqual(store.load("gemini"), "")
        store.clear("gemini")  # clearing twice is harmless

    def test_empty_key_refused(self):
        with self.assertRaises(ValueError):
            ApiKeyStore(FakeKeyring()).save("gemini", "   ")

    def test_environment_variable_used_when_nothing_saved(self):
        store = ApiKeyStore(FakeKeyring())
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "from-env"}):
            self.assertEqual(store.load("gemini", "GEMINI_API_KEY"), "from-env")
            store.save("gemini", "saved")
            self.assertEqual(store.load("gemini", "GEMINI_API_KEY"), "saved")

    def test_storage_failure_is_a_plain_error(self):
        with self.assertRaises(KeyStorageError):
            ApiKeyStore(BrokenKeyring()).save("gemini", "abc")

    def test_masked(self):
        self.assertEqual(ApiKeyStore.masked("AIzaSyExample1234"), "AIza…1234")
        self.assertEqual(ApiKeyStore.masked("short"), "•••••")
