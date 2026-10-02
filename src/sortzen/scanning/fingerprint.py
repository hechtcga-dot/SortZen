"""Content fingerprints that identify a file wherever it is moved or renamed.

Small files are hashed whole. Large files are hashed from their size plus three 64 KB
samples (start, middle, end), so a 4 GB video takes as long as a 192 KB one.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

SAMPLE = 64 * 1024


def fingerprint(path: Path, size: int | None = None) -> str:
    path = Path(path)
    size = path.stat().st_size if size is None else size
    digest = hashlib.blake2b(digest_size=16)
    digest.update(str(size).encode("ascii"))
    with path.open("rb") as f:
        if size <= 3 * SAMPLE:
            digest.update(f.read())
        else:
            for offset in (0, size // 2 - SAMPLE // 2, size - SAMPLE):
                f.seek(offset)
                digest.update(f.read(SAMPLE))
    return digest.hexdigest()
