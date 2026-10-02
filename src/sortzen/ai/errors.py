"""Plain explanations of what went wrong when an AI service is asked."""
from __future__ import annotations

_MISSING_MODEL = ("404", "not_found", "not found", "does not exist", "model_not_found", "unknown model",
                  "invalid model", "no such model", "is not a valid model", "not supported for generatecontent")
_BAD_KEY = ("401", "403", "api key", "api_key", "unauthorized", "unauthenticated", "permission_denied",
            "authentication", "refused the api key")
_UNREACHABLE = ("couldn't reach", "unavailable)", "urlopen error", "timed out", "timeout", "connection",
                "name or service not known", "getaddrinfo", "network")
_BUSY = ("429", "resource_exhausted", "quota", "rate limit", "too many requests")


class AIProblem(RuntimeError):
    """An AI service problem, already explained in plain words."""


def explain(exc: BaseException, service: str, model: str) -> str:
    """What went wrong, in words users can act on, e.g. "Gemini can't find the model “x”"."""
    if isinstance(exc, AIProblem):
        return str(exc)
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(t in text for t in _BAD_KEY):
        return (f"{service} didn't accept the API key. Check it in Settings › AI (copy the whole key, with no "
                "spaces), or make a new one.")
    if any(t in text for t in _MISSING_MODEL):
        return (f"{service} can't find the model “{model}”. Choose a model from the list in Settings › AI, or "
                f"click “Get the list from {service}” to see the names {service} offers.")
    if any(t in text for t in _BUSY):
        return (f"{service} is busy or this key has reached its limit for now. Try again in a few minutes, or "
                "check the key's plan and billing.")
    if any(t in text for t in _UNREACHABLE):
        if service == "Ollama":
            return "SortZen can't reach Ollama on this PC. Start Ollama, then try again."
        return f"SortZen can't reach {service}. Check the internet connection, then try again."
    detail = str(exc).strip().splitlines()[0][:300] if str(exc).strip() else type(exc).__name__
    return f"{service} returned an error: {detail}"
