"""Independently compare retained actual artist data with exact result rows."""

import csv, gzip, hashlib, io, json
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    rows = list(
        csv.DictReader(
            io.StringIO(
                gzip.decompress(
                    (ROOT / "results/held-metrics.csv.gz").read_bytes()
                ).decode()
            )
        )
    )
    values = {
        (r["carrier"], int(r["year"]), r["scenario"], r["view"], r["metric"]): Fraction(
            int(r["numerator"]), int(r["denominator"])
        )
        for r in rows
        if r["month"] == "annual" and r["defined"] == "1"
    }
    artists = json.loads(
        (ROOT / "figures/ARTIST_VALUES.json").read_text(encoding="utf-8")
    )
    primary = [(c, y) for y in [2023, 2024, 2025] for c in ["UA", "WN"]]
    all_cases = [(c, y) for y in [2023, 2024, 2025] for c in ["AA", "DL", "UA", "WN"]]
    checks = 0

    def scalar(got, want):
        nonlocal checks
        assert abs(float(got) - float(want)) < 1e-9, (got, want)
        checks += 1

    for name, cases, left, right in [
        (
            "denominator_rates",
            primary,
            ("airport_standardized", "scheduled_ontime"),
            ("airport_standardized", "completed_ontime"),
        ),
        (
            "airport_mix",
            all_cases,
            ("airport_standardized", "scheduled_ontime"),
            ("observed_pooled", "scheduled_ontime"),
        ),
    ]:
        item = artists[name]
        assert item["cases"] == [f"{c}-{y}" for c, y in cases]
        lkey, rkey = (
            ("scheduled_offsets", "completed_offsets")
            if name == "denominator_rates"
            else ("standardized_offsets", "pooled_offsets")
        )
        for i, (c, y) in enumerate(cases):
            a = values[(c, y, "0", *left)] * 100
            b = values[(c, y, "0", *right)] * 100
            for pair, expected in [(item[lkey][i], (a, i)), (item[rkey][i], (b, i))]:
                for got, want in zip(pair, expected):
                    scalar(got, want)
            for pair, expected in zip(item["segments"][i], [(a, i), (b, i)]):
                for got, want in zip(pair, expected):
                    scalar(got, want)
            if name == "denominator_rates":
                assert item["gap_annotations"][i] == f"+{float(b-a):.2f} pp"
    heat = artists["synthetic_conversion"]
    assert heat["cases"] == [f"{c}-{y}" for c, y in primary]
    scenarios = ["0", "1/10", "1/4", "1/2"]
    assert heat["scenarios"] == scenarios
    for i, (c, y) in enumerate(primary):
        for j, q in enumerate(scenarios):
            expected = (
                values[c, y, q, "airport_standardized", "completed_ontime"]
                - values[c, y, "0", "airport_standardized", "completed_ontime"]
            ) * 100
            scalar(heat["matrix"][i][j], expected)
    minimum = 100
    assert len(heat["annotations"]) == 24
    for a in heat["annotations"]:
        value = heat["matrix"][a["row"]][a["col"]]
        assert a["text"] == f"{value:.2f}"
        linear = [
            v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
            for v in a["background"][:3]
        ]
        lum = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
        contrast = (lum + 0.05) / 0.05 if a["color"] == "black" else 1.05 / (lum + 0.05)
        assert abs(contrast - a["contrast"]) < 1e-10 and contrast >= 4.5
        minimum = min(minimum, contrast)
    hashes = json.loads((ROOT / "figures/MANIFEST.json").read_text(encoding="utf-8"))
    assert len(hashes) == 9
    for name, digest in hashes.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    receipt = dict(
        status="PASS",
        actual_artist_numeric_values=checks,
        gap_annotations=6,
        heatmap_annotations=24,
        heatmap_contrast_checks=24,
        minimum_annotation_contrast=minimum,
        export_hashes=9,
        scope="Finite numeric artist/annotation/hash checks plus separate visual review; no accessibility-conformance claim.",
    )
    (ROOT / "figures/VERIFICATION.json").write_bytes(
        (json.dumps(receipt, indent=2) + "\n").encode()
    )
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
