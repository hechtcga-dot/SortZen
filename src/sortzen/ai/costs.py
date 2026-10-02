"""Rough prices for estimates and the spending cap, in US dollars per million tokens (input, output).

Actual spending is counted from the token usage each service reports. Unknown models use their
service's price, so estimates err on the high side.
"""
from __future__ import annotations

PRICES = {
    "gemini": (0.30, 2.50),
    "claude": (1.00, 5.00),
    "openai": (0.25, 2.00),
    "openrouter": (0.0, 0.0),           # ":free" models; paid ones are charged on OpenRouter's side
    "ollama": (0.0, 0.0),               # runs on this PC
}
CHARS_PER_TOKEN = 4


def tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN + 1


def cost(service: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES.get(service, PRICES["gemini"])
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000
