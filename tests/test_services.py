import tempfile
import unittest
from pathlib import Path

from sortzen.ai.web_providers import OllamaProvider
from sortzen.config import AppPaths
from sortzen.services import AppService
from tests.test_repositories import FakeKeyring
from sortzen.repositories.api_keys import ApiKeyStore


class AppServiceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.paths = AppPaths(Path(self.dir.name))
        self.service = AppService(self.paths, ApiKeyStore(FakeKeyring()))

    def tearDown(self):
        self.dir.cleanup()

    def test_gemini_is_the_default(self):
        self.assertEqual(self.service.ai_service(), "gemini")

    def test_choose_service(self):
        self.service.set_ai_service("claude")
        self.assertEqual(AppService(self.paths, self.service.keys).ai_service(), "claude")
        with self.assertRaises(ValueError):
            self.service.set_ai_service("nonsense")

    def test_unknown_saved_service_falls_back_to_default(self):
        self.service.settings.set("ai_service", "gone")
        self.assertEqual(self.service.ai_service(), "gemini")

    def test_model_override_and_reset(self):
        default = self.service.model()
        self.service.set_model("custom-model")
        self.assertEqual(self.service.model(), "custom-model")
        self.service.set_model("")
        self.assertEqual(self.service.model(), default)

    def test_keys_never_written_to_settings(self):
        self.service.save_api_key("secret-key-value")
        self.service.set_model("custom-model")
        self.assertTrue(self.service.has_api_key())
        self.assertNotIn("secret-key-value", self.paths.settings_path.read_text(encoding="utf-8"))

    def test_ollama_needs_no_key(self):
        self.service.set_ai_service("ollama")
        self.assertTrue(self.service.has_api_key())
        self.assertIsInstance(self.service.provider(), OllamaProvider)

    def test_missing_key_is_a_plain_error(self):
        self.service.set_ai_service("claude")
        with self.assertRaises(ValueError):
            self.service.provider()
