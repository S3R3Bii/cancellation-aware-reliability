"""Verify canonical fixed analytical dependencies before held computation."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify():
    frozen = json.loads((ROOT / "FREEZE.json").read_text(encoding="utf-8"))
    for name, digest in frozen["sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    return dict(
        status="PASS",
        dependencies=len(frozen["sha256"]),
        source_commit=frozen["source_commit"],
    )


if __name__ == "__main__":
    print(json.dumps(verify()))
