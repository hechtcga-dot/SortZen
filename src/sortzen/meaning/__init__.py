"""Matching by meaning, on the PC: a small static embedding model turns text into numbers that are close
when the meaning is close ("pay stub" and "Payroll"), with no network and no special hardware."""
from .embedder import MODEL_DIR, StaticEmbedder, load

__all__ = ["MODEL_DIR", "StaticEmbedder", "load"]
