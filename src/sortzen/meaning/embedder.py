"""A static embedding model: each word piece has a fixed vector; a text's vector is the average of its
pieces' vectors, scaled to length 1. Reading thousands of files' vectors takes about a second.

The model (tokenizer.json, model.safetensors, config.json) is bundled with the program in
``meaning/model``; ``packaging/get_meaning_model.py`` downloads it before a build.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

log = logging.getLogger("sortzen")

MODEL_DIR = Path(__file__).resolve().parent / "model"
MAX_TOKENS = 256            # word pieces read per text


class StaticEmbedder:
    def __init__(self, folder: Path):
        import numpy as np
        from safetensors.numpy import load_file
        from tokenizers import Tokenizer

        self.np = np
        self.tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))
        self.tokenizer.no_padding()
        self.tokenizer.no_truncation()
        tensors = load_file(str(folder / "model.safetensors"))
        self.vectors = np.asarray(tensors.get("embeddings", next(iter(tensors.values()))), dtype=np.float32)
        config = json.loads((folder / "config.json").read_text(encoding="utf-8")) \
            if (folder / "config.json").exists() else {}
        self.normalize = bool(config.get("normalize", True))
        self.unknown = self.tokenizer.token_to_id("[UNK]")
        self.dim = self.vectors.shape[1]

    def embed(self, texts: list[str]):
        """One row per text, each of length 1 (or all zeros for a text with no known words)."""
        np = self.np
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        if not texts:
            return out
        for row, encoding in enumerate(self.tokenizer.encode_batch([t or "" for t in texts],
                                                                   add_special_tokens=False)):
            ids = [i for i in encoding.ids[:MAX_TOKENS] if i != self.unknown and i < len(self.vectors)]
            if ids:
                out[row] = self.vectors[ids].mean(axis=0)
        lengths = np.linalg.norm(out, axis=1, keepdims=True)
        return np.divide(out, lengths, out=np.zeros_like(out), where=lengths > 0)


_loaded: StaticEmbedder | None = None
_why_not = ""


def model_folder() -> Path:
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "sortzen" / "meaning" / "model"
    return bundled if (bundled / "tokenizer.json").exists() else MODEL_DIR


def load() -> StaticEmbedder | None:
    """The model, loaded once; None (with why_unavailable()) when it isn't installed."""
    global _loaded, _why_not
    if _loaded is None and not _why_not:
        folder = model_folder()
        try:
            _loaded = StaticEmbedder(folder)
        except Exception as exc:      # no model or a missing library: matching by meaning is skipped
            _why_not = f"The meaning model isn't available ({type(exc).__name__}: {exc})"
            log.warning(_why_not)
    return _loaded


def why_unavailable() -> str:
    load()
    return _why_not
