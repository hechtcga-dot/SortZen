"""The AI services SortZen can use: one list for Settings, first setup and the services layer."""
from __future__ import annotations

from dataclasses import dataclass

from ..config import MODEL_DEFAULT


@dataclass(frozen=True)
class AIService:
    key: str
    name: str              # short, for messages: "AI service: Claude"
    caption: str           # for the drop-down
    needs_key: bool
    default_model: str
    key_env: str           # environment variable read when no key is saved
    how_to: str            # HTML steps to get a key


SERVICES = {
    "gemini": AIService(
        "gemini", "Gemini", "Google Gemini (recommended, low cost)", True, MODEL_DEFAULT, "GEMINI_API_KEY",
        "1. Go to <b>aistudio.google.com</b> and sign in with a Google account.<br>"
        "2. Click <b>Get API key</b>, then <b>Create API key</b>.<br>"
        "3. Copy the key and paste it below."),
    "claude": AIService(
        "claude", "Claude", "Anthropic Claude", True, "claude-haiku-4-5", "ANTHROPIC_API_KEY",
        "1. Go to <b>console.anthropic.com</b> and create an account.<br>"
        "2. Add a payment method under <b>Billing</b> (paid per use).<br>"
        "3. Open <b>API keys</b>, click <b>Create key</b>, copy it and paste it below."),
    "openai": AIService(
        "openai", "ChatGPT", "OpenAI ChatGPT", True, "gpt-5-mini", "OPENAI_API_KEY",
        "1. Go to <b>platform.openai.com</b> and sign in.<br>"
        "2. Add a payment method under <b>Billing</b> (the API is paid per use, separate from a "
        "ChatGPT subscription).<br>"
        "3. Open <b>API keys</b>, click <b>Create new secret key</b>, copy it and paste it below."),
    "openrouter": AIService(
        "openrouter", "OpenRouter", "OpenRouter (some free models)", True, "google/gemma-3-27b-it:free",
        "OPENROUTER_API_KEY",
        "1. Go to <b>openrouter.ai</b> and create an account.<br>"
        "2. Open <b>Keys</b>, create a key, copy it and paste it below.<br>"
        "3. Models whose name ends in <b>:free</b> cost nothing but have daily limits."),
    "ollama": AIService(
        "ollama", "Ollama", "Ollama (free, runs on this PC)", False, "llama3.2", "",
        "1. Download Ollama from <b>ollama.com</b> and install it.<br>"
        "2. In a command window run <b>ollama pull llama3.2</b>.<br>"
        "No key is needed and nothing leaves this PC. It is slower than the online services "
        "and needs a reasonably fast computer."),
}
DEFAULT_SERVICE = "gemini"
OLLAMA_URL = "http://localhost:11434"


def make_provider(service: str, api_key: str, ollama_url: str = OLLAMA_URL):
    if service == "claude":
        from .web_providers import ClaudeProvider
        return ClaudeProvider(api_key)
    if service == "openai":
        from .web_providers import OpenAICompatibleProvider
        return OpenAICompatibleProvider(api_key, "https://api.openai.com/v1", "ChatGPT")
    if service == "openrouter":
        from .web_providers import OpenAICompatibleProvider
        return OpenAICompatibleProvider(api_key, "https://openrouter.ai/api/v1", "OpenRouter", json_mode=False)
    if service == "ollama":
        from .web_providers import OllamaProvider
        return OllamaProvider(ollama_url)
    from .gemini import GeminiAIProvider
    return GeminiAIProvider(api_key)
