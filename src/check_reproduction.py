"""Regenerate both declared stages in an isolated checkout and match exact fields."""

import csv
import gzip
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from verify_freeze import verify

ROOT = Path(__file__).resolve().parents[1]


def main():
    frozen = verify()
    names = [
        "results/source-resolution.csv",
        "results/cohort.csv",
        "results/weights.csv",
    ]
    for stage in ["development", "held"]:
        names += [
            "results/" + stage + "-" + n
            for n in [
                "panel-airports.csv",
                "coverage.csv",
                "airport-counts.csv.gz",
                "metrics.csv.gz",
                "SUMMARY.json",
                "VERIFICATION.json",
            ]
        ]
    expected = {name: (ROOT / name).read_bytes() for name in names}
    fields = 0
    documents = 0
    with tempfile.TemporaryDirectory(prefix="airport03-replay-") as folder:
        temp = Path(folder) / "study"
        shutil.copytree(
            ROOT, temp, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv")
        )
        for name in names:
            (temp / name).unlink()
        for stage in ["development", "held"]:
            for script in ["run_analysis.py", "verify_results.py"]:
                result = subprocess.run(
                    [sys.executable, str(temp / "src" / script), stage],
                    cwd=temp,
                    capture_output=True,
                    text=True,
                )
                assert result.returncode == 0, result.stdout + result.stderr
        for name, data in expected.items():
            fresh = (temp / name).read_bytes()
            if name.endswith(".gz"):
                fresh = gzip.decompress(fresh)
                data = gzip.decompress(data)
            assert fresh == data, name
            if ".csv" in name:
                rows = list(csv.reader(io.StringIO(data.decode())))
                fields += (len(rows) - 1) * len(rows[0])
            else:
                documents += 1
        for name, digest in json.loads(
            (ROOT / "FREEZE.json").read_text(encoding="utf-8")
        )["sha256"].items():
            import hashlib

            assert (
                hashlib.sha256((temp / name).read_bytes()).hexdigest() == digest
            ), name
    record = dict(
        status="PASS",
        exact_csv_fields=fields,
        verification_and_summary_documents=documents,
        protected_dependencies=frozen["dependencies"],
        scope="Exact isolated replay of declared captured-input stages; no live availability, causal or source-truth claim.",
    )
    (ROOT / "REPROCHECK.json").write_bytes(
        (json.dumps(record, indent=2) + "\n").encode()
    )
    print(json.dumps(record))


if __name__ == "__main__":
    main()
