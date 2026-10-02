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
