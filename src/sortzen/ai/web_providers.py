"""Claude, ChatGPT (OpenAI), OpenRouter and Ollama adapters.

They call each service's web API directly with the standard library, so no extra packages
are needed, and implement the same ``AIProvider`` boundary as Gemini.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

from .provider import AIProvider, AIResponse, ContentPart, ImagePayload, TokenUsage

TIMEOUT = 300
LIST_TIMEOUT = 20
MAX_OUTPUT_TOKENS = 8000


class AIServiceError(RuntimeError):
    """A plain message for users; busy-service errors keep the words retries look for."""


def _post(url, body, headers, service):
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:
            return json.loads(reply.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        if exc.code in (401, 403):
            raise AIServiceError(f"{service} refused the API key ({exc.code}). Check it in Settings › AI. {detail}")
        raise AIServiceError(f"{service} error {exc.code}: {detail}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AIServiceError(f"Couldn't reach {service} (unavailable): {exc}")


def _get(url, headers, service):
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=LIST_TIMEOUT) as reply:
            return json.loads(reply.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        if exc.code in (401, 403):
            raise AIServiceError(f"{service} refused the API key ({exc.code}). {detail}")
        raise AIServiceError(f"{service} error {exc.code}: {detail}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AIServiceError(f"Couldn't reach {service} (unavailable): {exc}")


_NOT_CHAT = ("embedding", "tts", "whisper", "dall-e", "audio", "realtime", "moderation", "image", "transcribe",
             "search", "davinci", "babbage")


def _b64(image: ImagePayload) -> str:
    return base64.b64encode(image.data).decode("ascii")


class ClaudeProvider(AIProvider):
    provider_name = "Claude"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str):
        self.api_key = (api_key or "").strip()
        if not self.api_key:
            raise ValueError("Enter your Claude API key first (Settings › AI).")

    def generate_json(self, model: str, contents: list[ContentPart]) -> AIResponse:
        parts = []
        for p in contents:
            if isinstance(p, ImagePayload):
                parts.append({"type": "image", "source": {"type": "base64", "media_type": p.mime_type, "data": _b64(p)}})
            else:
                parts.append({"type": "text", "text": p})
        data = _post(self.URL, {"model": model, "max_tokens": MAX_OUTPUT_TOKENS,
                                "messages": [{"role": "user", "content": parts}]},
                     {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}, "Claude")
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        u = data.get("usage") or {}
        i, o = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
        return AIResponse(text=text, usage=TokenUsage(i, o, i + o))


    def list_models(self) -> list[str]:
        data = _get("https://api.anthropic.com/v1/models?limit=100",
                    {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}, "Claude")
        return [m["id"] for m in data.get("data") or [] if m.get("id")]


class OpenAICompatibleProvider(AIProvider):
    """OpenAI's chat completions format, used by ChatGPT and OpenRouter."""

    def __init__(self, api_key: str, base_url: str, name: str, json_mode: bool = True):
        self.api_key = (api_key or "").strip()
        self.provider_name = name
        if not self.api_key:
            raise ValueError(f"Enter your {name} API key first (Settings › AI).")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.json_mode = json_mode

    def generate_json(self, model: str, contents: list[ContentPart]) -> AIResponse:
        parts = []
        for p in contents:
            if isinstance(p, ImagePayload):
                parts.append({"type": "image_url", "image_url": {"url": f"data:{p.mime_type};base64,{_b64(p)}"}})
            else:
                parts.append({"type": "text", "text": p})
        body = {"model": model, "messages": [{"role": "user", "content": parts}]}
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        data = _post(self.url, body, {"Authorization": f"Bearer {self.api_key}"}, self.provider_name)
        choices = data.get("choices") or []
        if not choices:
            raise AIServiceError(f"{self.provider_name} returned no answer: {str(data)[:300]}")
        text = (choices[0].get("message") or {}).get("content") or ""
        u = data.get("usage") or {}
        i, o = int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
        return AIResponse(text=text, usage=TokenUsage(i, o, int(u.get("total_tokens") or i + o)))


    def list_models(self) -> list[str]:
        data = _get(self.url.rsplit("/chat/completions", 1)[0] + "/models",
                    {"Authorization": f"Bearer {self.api_key}"}, self.provider_name)
        ids = [m["id"] for m in data.get("data") or [] if m.get("id")]
        ids = [i for i in ids if not any(word in i.lower() for word in _NOT_CHAT)]
        return sorted(ids, key=lambda i: (not i.endswith(":free"), i)) if self.provider_name == "OpenRouter" \
            else sorted(ids)


class OllamaProvider(AIProvider):
    """Ollama runs the model on this PC: no key, no cost, nothing leaves the computer."""

    provider_name = "Ollama"

    def __init__(self, url: str = "http://localhost:11434"):
        self.base = (url or "http://localhost:11434").rstrip("/")
        self.url = self.base + "/api/chat"

    def list_models(self) -> list[str]:
        data = _get(self.base + "/api/tags", {}, "Ollama")
        return [m["name"] for m in data.get("models") or [] if m.get("name")]

    def generate_json(self, model: str, contents: list[ContentPart]) -> AIResponse:
        # Ollama attaches images to messages, so each text keeps the images that follow it.
        messages = []
        for p in contents:
            if isinstance(p, ImagePayload):
                if not messages:
                    messages.append({"role": "user", "content": "", "images": []})
                messages[-1]["images"].append(_b64(p))
            else:
                messages.append({"role": "user", "content": p, "images": []})
        data = _post(self.url, {"model": model, "messages": messages, "stream": False, "format": "json"}, {},
                     "Ollama")
        text = (data.get("message") or {}).get("content") or ""
        i, o = int(data.get("prompt_eval_count") or 0), int(data.get("eval_count") or 0)
        return AIResponse(text=text, usage=TokenUsage(i, o, i + o))
