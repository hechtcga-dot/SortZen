"""Download the meaning model into src/sortzen/meaning/model before a build (needs the internet once).

    python packaging/get_meaning_model.py

The model is potion-base-8M by Minish (MIT licence): a static embedding model of about 30 MB.
"""
import hashlib
import sys
import urllib.request
from pathlib import Path

REPO = "minishlab/potion-base-8M"
REVISION = "main"
FILES = ("config.json", "tokenizer.json", "model.safetensors", "README.md")
TARGET = Path(__file__).resolve().parent.parent / "src" / "sortzen" / "meaning" / "model"


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        path = TARGET / name
        if path.exists() and path.stat().st_size > 0:
            print(f"have {name}")
            continue
        url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}"
        print(f"getting {url}")
        with urllib.request.urlopen(url, timeout=300) as reply:
            data = reply.read()
        path.write_bytes(data)
        print(f"  {len(data):,} bytes, sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
