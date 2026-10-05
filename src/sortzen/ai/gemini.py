"""Google Gemini adapter (google-genai SDK, imported lazily)."""
from __future__ import annotations

from .provider import AIProvider, AIResponse, ContentPart, ImagePayload, TokenUsage


class GeminiAIProvider(AIProvider):
    provider_name = "Gemini"

    def __init__(self, api_key, client=None, types_module=None):
        self.api_key = (api_key or "").strip()
        if not self.api_key:
            raise ValueError("Enter your Gemini API key first (Settings › AI).")
        if types_module is None:
            from google.genai import types as types_module

        self._types = types_module
        if client is None:
            from google import genai

            client = genai.Client(api_key=self.api_key)
        self.client = client

    def _to_sdk(self, part: ContentPart):
        if isinstance(part, ImagePayload):
            return self._types.Part.from_bytes(data=part.data, mime_type=part.mime_type)
        return part

    def generate_json(self, model, contents):
        response = self.client.models.generate_content(
            model=model,
            contents=[self._to_sdk(p) for p in contents],
            config=self._types.GenerateContentConfig(response_mime_type="application/json"),
        )
        meta = getattr(response, "usage_metadata", None)
        usage = TokenUsage(
            input_tokens=int(getattr(meta, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(meta, "candidates_token_count", 0) or 0),
            total_tokens=int(getattr(meta, "total_token_count", 0) or 0),
        )
        return AIResponse(text=response.text, usage=usage)

    def list_models(self) -> list[str]:
        """Gemini models that can answer requests like SortZen's."""
        found = []
        for m in self.client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if actions and "generateContent" not in actions:
                continue
            name = str(getattr(m, "name", "") or "")
            name = name.split("/", 1)[1] if name.startswith("models/") else name
            if name and not any(w in name for w in ("embedding", "imagen", "veo", "aqa", "tts", "image")):
                found.append(name)
        return sorted(found)
