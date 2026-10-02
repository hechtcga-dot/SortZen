import unittest
from types import SimpleNamespace
from unittest import mock

from sortzen.ai import ImagePayload, is_transient_api_error
from sortzen.ai import web_providers
from sortzen.ai.gemini import GeminiAIProvider
from sortzen.ai.parsing import extract_json
from sortzen.ai.services import SERVICES, make_provider


class ParsingTest(unittest.TestCase):
    def test_plain_fenced_and_wrapped_json(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('Here you go: {"a": 1} done'), {"a": 1})

    def test_no_json_raises(self):
        with self.assertRaises(ValueError):
            extract_json("no json here")

    def test_transient_errors(self):
        self.assertTrue(is_transient_api_error(RuntimeError("503 UNAVAILABLE")))
        self.assertTrue(is_transient_api_error(RuntimeError("429 Too Many Requests")))
        self.assertFalse(is_transient_api_error(RuntimeError("400 bad request")))


class ProviderTest(unittest.TestCase):
    def test_every_service_has_a_provider(self):
        for key, info in SERVICES.items():
            provider = make_provider(key, "test-key")
            self.assertTrue(provider.provider_name)
            self.assertTrue(info.default_model)
            self.assertEqual(info.needs_key, key != "ollama")

    def test_claude_request_and_reply(self):
        reply = {"content": [{"type": "text", "text": '{"ok": true}'}], "usage": {"input_tokens": 10, "output_tokens": 3}}
        with mock.patch.object(web_providers, "_post", return_value=reply) as post:
            result = web_providers.ClaudeProvider("k").generate_json("m", ["hello", ImagePayload(b"x")])
        body = post.call_args.args[1]
        self.assertEqual([p["type"] for p in body["messages"][0]["content"]], ["text", "image"])
        self.assertEqual(result.text, '{"ok": true}')
        self.assertEqual(result.usage.total_tokens, 13)

    def test_openai_compatible_reply(self):
        reply = {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
        with mock.patch.object(web_providers, "_post", return_value=reply) as post:
            result = web_providers.OpenAICompatibleProvider("k", "https://x/v1", "ChatGPT").generate_json("m", ["hi"])
        self.assertEqual(post.call_args.args[0], "https://x/v1/chat/completions")
        self.assertEqual(post.call_args.args[1]["response_format"], {"type": "json_object"})
        self.assertEqual(result.usage.total_tokens, 7)

    def test_openai_compatible_without_answer(self):
        with mock.patch.object(web_providers, "_post", return_value={"choices": []}):
            with self.assertRaises(web_providers.AIServiceError):
                web_providers.OpenAICompatibleProvider("k", "https://x/v1", "ChatGPT").generate_json("m", ["hi"])

    def test_ollama_keeps_images_with_their_text(self):
        reply = {"message": {"content": "{}"}, "prompt_eval_count": 4, "eval_count": 1}
        with mock.patch.object(web_providers, "_post", return_value=reply) as post:
            web_providers.OllamaProvider().generate_json("m", ["a", ImagePayload(b"1"), "b"])
        messages = post.call_args.args[1]["messages"]
        self.assertEqual([(m["content"], len(m["images"])) for m in messages], [("a", 1), ("b", 0)])

    def test_gemini_reply_and_usage(self):
        response = SimpleNamespace(text="{}", usage_metadata=SimpleNamespace(
            prompt_token_count=8, candidates_token_count=2, total_token_count=10))
        client = SimpleNamespace(models=SimpleNamespace(generate_content=mock.Mock(return_value=response)))
        types = SimpleNamespace(GenerateContentConfig=lambda **kw: kw,
                                Part=SimpleNamespace(from_bytes=lambda **kw: ("image", kw["mime_type"])))
        result = GeminiAIProvider("k", client=client, types_module=types).generate_json("m", ["hi", ImagePayload(b"x")])
        self.assertEqual(result.usage.total_tokens, 10)
        sent = client.models.generate_content.call_args.kwargs["contents"]
        self.assertEqual(sent, ["hi", ("image", "image/jpeg")])

    def test_missing_key_refused(self):
        with self.assertRaises(ValueError):
            web_providers.ClaudeProvider("")


import json
import os
import shutil
import tempfile
from pathlib import Path

from sortzen.ai import privacy
from sortzen.ai.provider import AIProvider, AIResponse, TokenUsage
from sortzen.ai.sorter import AIFile, AIFolder, AISorter
from sortzen.engine.ai_evidence import apply_ai
from sortzen.engine.plan import Plan, Reason, Suggestion
from sortzen.repositories.ai_answers import AIAnswer


class FakeProvider(AIProvider):
    """Answers every file with a chosen folder and sureness; records what it was sent."""

    provider_name = "Fake"

    def __init__(self, choose=lambda name, content: (1, 80), fail=()):
        self.choose = choose
        self.sent = []
        self.fail = list(fail)

    def generate_json(self, model, contents):
        if self.fail:
            raise self.fail.pop(0)
        self.sent.append(contents)
        text = "\n".join(p for p in contents if isinstance(p, str))
        content = "Beginning of the file" in text
        files = []
        for line in text.splitlines():
            if line.startswith("f") and ": “" in line:
                fid, rest = line.split(": “", 1)
                folder, sure = self.choose(rest.split("”")[0], content)
                files.append({"id": fid, "folder": folder, "sure": sure, "why": "fake"})
        return AIResponse(json.dumps({"files": files}), TokenUsage(1000, 100, 1100))


class PrivacyTest(unittest.TestCase):
    def test_scrub_keeps_words_and_years(self):
        text = privacy.scrub("Pay 4111 1111 1111 1111 to jo@example.com by 2024, ref 88231, invoice 12")
        self.assertNotIn("4111", text)
        self.assertNotIn("example.com", text)
        self.assertNotIn("88231", text)
        self.assertIn("2024", text)
        self.assertIn("invoice 12", text)
        self.assertEqual(privacy.scrub_name("Statement 0012345678.pdf"), "Statement #.pdf")

    def test_name_only_folders_and_words(self):
        self.assertTrue(privacy.name_only("/d/Taxes/a.pdf", ["/d/Taxes"], []))
        self.assertTrue(privacy.name_only("/d/My Bank letter.pdf", [], ["bank"]))
        self.assertFalse(privacy.name_only("/d/Garden notes.docx", ["/d/Taxes"], ["bank"]))
        self.assertEqual(len(privacy.beginning("word " * 1000).split()), privacy.WORDS_SENT)


class SorterTest(unittest.TestCase):
    folders = [AIFolder("/s/Work", "Sorted/Work", ["Payroll March.xlsx"]), AIFolder("/s/Home", "Sorted/Home")]

    def files(self, n=3, text="some words"):
        return [AIFile(f"k{i}", f"/d/file{i}.docx", f"file{i}.docx", "Downloads", text if i else "") for i in range(n)]

    def test_two_passes_only_unsure_files_with_content(self):
        provider = FakeProvider(lambda name, content: (2, 90) if content else (1, 40 if name != "file0.docx" else 95))
        answers, run = AISorter(provider, "gemini", "m", "Resumes are personal").run(self.folders, self.files(), 1.0)
        self.assertEqual(len(provider.sent), 2)
        self.assertIn("House rules", provider.sent[0][0])
        self.assertEqual((run.asked, run.second_pass), (3, 2))
        self.assertEqual(answers["k0"], AIAnswer("/s/Work", 95, "fake", False, "gemini"))
        self.assertEqual(answers["k1"].destination, "/s/Home")
        self.assertTrue(answers["k1"].content)
        self.assertGreater(run.spent, 0)

    def test_null_folder_bad_reply_and_cap(self):
        answers, _ = AISorter(FakeProvider(lambda n, c: (None, 90)), "gemini", "m").run(self.folders, self.files(1), 1.0)
        self.assertIsNone(answers["k0"].destination)
        bad = FakeProvider()
        bad.generate_json = lambda model, contents: AIResponse("not json")
        answers, _ = AISorter(bad, "gemini", "m").run(self.folders, self.files(), 1.0)
        self.assertEqual(answers, {})
        answers, run = AISorter(FakeProvider(), "gemini", "m", batch_size=1).run(self.folders, self.files(), 0.0)
        self.assertIn("spending cap", run.stopped)
        self.assertEqual(answers, {})

    def test_busy_service_is_retried(self):
        provider = FakeProvider(fail=[RuntimeError("503 UNAVAILABLE")])
        answers, run = AISorter(provider, "gemini", "m", sleep=lambda s: None).run(self.folders, self.files(1, ""), 1.0)
        self.assertEqual(run.stopped, "")
        self.assertIn("k0", answers)

    def test_estimate_within_the_cost_target(self):
        files = [AIFile(f"k{i}", f"/d/f{i}", f"Invoice from Northgate {i}.pdf", "Downloads", "word " * 400)
                 for i in range(1000)]
        folders = [AIFolder(f"/s/{i}", f"Sorted/Folder {i}", ["a.pdf", "b.pdf", "c.pdf"]) for i in range(60)]
        self.assertLess(AISorter(None, "gemini", "m").estimate(folders, files), 0.75)


class EvidenceTest(unittest.TestCase):
    def test_agree_alone_and_corrections(self):
        plan = Plan(files=[Suggestion("/d/a", "/d", "/s/Work", 60), Suggestion("/d/b", "/d", None, 0),
                           Suggestion("/d/c", "/d", "/s/Work", 100, [Reason(True, "You chose this folder")]),
                           Suggestion("/d/e", "/d", "/s/Work", 80)])
        answers = {p: AIAnswer("/s/Work" if p != "/d/b" else "/s/Home", 90, "looks like work", service="gemini")
                   for p in ("/d/a", "/d/b", "/d/c")}
        answers["/d/e"] = AIAnswer("/s/Home", 95, service="gemini")
        apply_ai(plan, answers, lambda f: True, {"gemini": "Gemini"})
        a, b, c, e = plan.files
        self.assertEqual(a.percent, 78)                      # 60 + 40 * 0.5 * 0.9
        self.assertIn("Gemini also chose", a.reasons[0].text)
        self.assertEqual((b.destination, b.percent), ("/s/Home", 63))       # alone: at most 70
        self.assertEqual(c.percent, 100)
        self.assertEqual((e.destination, e.percent), ("/s/Work", 80))       # SortZen was surer
        self.assertIn("suggested “Home” instead", e.reasons[-1].text)


class AIServiceStepTest(unittest.TestCase):
    def setUp(self):
        from sortzen.config import AppPaths
        from sortzen.repositories.api_keys import ApiKeyStore
        from sortzen.services import AppService
        from tests.fixtures import shared_test_folders
        from tests.test_repositories import FakeKeyring

        self.dir = tempfile.TemporaryDirectory()
        root = shared_test_folders()
        self.service = AppService(AppPaths(Path(self.dir.name)), ApiKeyStore(FakeKeyring()))
        self.service.scanner.protected = []
        self.service.add_source(str(root / "Downloads"))
        self.service.add_destination(str(root / "Sorted"))
        self.plan = self.service.make_plan()

    def tearDown(self):
        self.dir.cleanup()

    def test_estimate_ask_remember_and_privacy(self):
        estimate = self.service.ai_estimate(self.plan)
        self.assertGreater(estimate["files"], 10)
        self.assertEqual(estimate["with_content"], 0)                    # name only by default
        self.assertLessEqual(estimate["cost"], estimate["cap"])
        provider = FakeProvider(lambda name, content: (1, 90))
        run = self.service.ask_ai(self.plan, provider=provider)
        self.assertEqual(run.asked, estimate["files"])
        self.assertFalse(any("Beginning of the file" in p for batch in provider.sent for p in batch
                             if isinstance(p, str)))
        self.assertGreater(self.service.ai_spent(), 0)
        again = self.service.make_plan()
        reasons = [r.text for s in again.files for r in s.reasons]
        self.assertTrue(any("Gemini" in t for t in reasons))
        self.assertEqual(self.service.ai_estimate(again)["files"], 0)    # remembered: never paid for twice
        self.service.forget_ai_answers()
        self.service.set_ai_value("ai_privacy", privacy.BEGINNING)
        self.service.set_ai_value("ai_name_only_words", ["resume"])
        files = self.service._ai_request(again)[1]
        self.assertTrue(any(f.text for f in files))
        self.assertFalse(any(f.text for f in files if "resume" in f.path.lower()))


class ErrorsAndModelsTest(unittest.TestCase):
    def test_plain_explanations(self):
        from sortzen.ai.errors import explain

        self.assertIn("can't find the model “gemini-x”",
                      explain(RuntimeError("404 NOT_FOUND models/gemini-x is not found"), "Gemini", "gemini-x"))
        self.assertIn("didn't accept the API key",
                      explain(web_providers.AIServiceError("Claude refused the API key (401)"), "Claude", "m"))
        self.assertIn("can't reach Ollama",
                      explain(web_providers.AIServiceError("Couldn't reach Ollama (unavailable): refused"),
                              "Ollama", "llama3.2"))
        self.assertIn("busy", explain(RuntimeError("429 RESOURCE_EXHAUSTED"), "Gemini", "m"))
        self.assertIn("returned an error: odd", explain(RuntimeError("odd"), "Gemini", "m"))

    def test_sorter_stops_with_the_explanation(self):
        class Missing(FakeProvider):
            def generate_json(self, model, contents):
                raise RuntimeError("404 model not found")

        files = [AIFile("k", "/d/a.pdf", "a.pdf", "Downloads")]
        _, run = AISorter(Missing(), "gemini", "gemini-typo").run([AIFolder("/s", "Sorted")], files, 1.0)
        self.assertTrue(run.failed)
        self.assertIn("Gemini can't find the model “gemini-typo”", run.stopped)

    def test_model_lists_from_each_service(self):
        replies = {
            "https://api.anthropic.com/v1/models?limit=100": {"data": [{"id": "claude-a"}]},
            "https://x/v1/models": {"data": [{"id": "gpt-small"}, {"id": "text-embedding-3"}, {"id": "a:free"}]},
            "http://localhost:11434/api/tags": {"models": [{"name": "llama3.2"}]},
        }
        with mock.patch.object(web_providers, "_get", lambda url, headers, service: replies[url]):
            self.assertEqual(web_providers.ClaudeProvider("k").list_models(), ["claude-a"])
            self.assertEqual(web_providers.OpenAICompatibleProvider("k", "https://x/v1", "OpenRouter").list_models(),
                             ["a:free", "gpt-small"])
            self.assertEqual(web_providers.OllamaProvider().list_models(), ["llama3.2"])
        models = [SimpleNamespace(name="models/gemini-a", supported_actions=["generateContent"]),
                  SimpleNamespace(name="models/text-embedding-004", supported_actions=["embedContent"])]
        client = SimpleNamespace(models=SimpleNamespace(list=lambda: models))
        self.assertEqual(GeminiAIProvider("k", client=client, types_module=SimpleNamespace()).list_models(),
                         ["gemini-a"])

    def test_service_check_fetch_and_choices(self):
        from sortzen.ai.errors import AIProblem
        from sortzen.config import AppPaths
        from sortzen.repositories.api_keys import ApiKeyStore
        from sortzen.services import AppService
        from tests.test_repositories import FakeKeyring

        with tempfile.TemporaryDirectory() as folder:
            service = AppService(AppPaths(Path(folder)), ApiKeyStore(FakeKeyring()))
            with self.assertRaises(AIProblem) as no_key:
                service.check_ai("gemini")
            self.assertIn("Paste your Gemini API key", str(no_key.exception))
            provider = FakeProvider()
            provider.list_models = lambda: ["gemini-b", "gemini-c"]
            with mock.patch("sortzen.services.app_service.make_provider", lambda *a: provider):
                service.check_ai("gemini", "gemini-b", key="typed")
                self.assertEqual(service.fetch_models("gemini", key="typed"), ["gemini-b", "gemini-c"])
            service.set_model("my-own-model", "gemini")
            self.assertEqual(service.model_choices("gemini"),
                             [SERVICES["gemini"].default_model, "gemini-b", "gemini-c", "my-own-model"])
