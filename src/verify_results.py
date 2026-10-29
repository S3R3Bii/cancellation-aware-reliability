"""Independent SQLite cohort/count reconstruction and rational outcome arithmetic."""

import argparse
from collections import defaultdict
import csv
from decimal import Decimal, localcontext
from fractions import Fraction as F
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def read_csv(name):
    data = (ROOT / name).read_bytes()
    if name.endswith(".gz"):
        data = gzip.decompress(data)
    return list(csv.DictReader(io.StringIO(data.decode())))


def display(value):
    if value is None:
        return ""
    with localcontext() as c:
        c.prec = max(60, len(str(value.numerator)) + len(str(value.denominator)) + 10)
        return format(
            (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
                Decimal("0.000000000000000001")
            ),
            "f",
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["development", "held"])
    args = ap.parse_args()
    cfg = json.loads((ROOT / "protocol.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (ROOT / "data/source/manifest.json").read_text(encoding="utf-8")
    )
    assert (
        hashlib.sha256(
            gzip.decompress((ROOT / manifest["projection_file"]).read_bytes())
        ).hexdigest()
        == manifest["projection_csv_sha256"]
    )
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE raw(c TEXT,y INT,m INT,a TEXT,n INT,d INT,k INT,v INT,PRIMARY KEY(c,y,a,m))"
    )
    cells = []
    for r in read_csv(manifest["projection_file"]):
        values = [
            int(r[k]) if r[k] else None
            for k in ["arr_flights", "arr_del15", "arr_cancelled", "arr_diverted"]
        ]
        assert all(v is None or v >= 0 for v in values)
        cells.append(
            (r["carrier"], int(r["year"]), int(r["month"]), r["airport"], *values)
        )
    db.executemany("INSERT INTO raw VALUES(?,?,?,?,?,?,?,?)", cells)
    db.execute(
        "CREATE VIEW resolved AS SELECT c,y,m,a,n,CASE WHEN d IS NULL AND n=k+v THEN 0 ELSE d END AS d,k,v FROM raw"
    )
    assert (
        db.execute(
            "SELECT COUNT(*) FROM resolved WHERE n>0 AND (d IS NULL OR k IS NULL OR v IS NULL OR d+k+v>n)"
        ).fetchone()[0]
        == 0
    )
    db.execute(
        "CREATE VIEW valid AS SELECT * FROM resolved WHERE n>0 AND d IS NOT NULL AND k IS NOT NULL AND v IS NOT NULL AND d+k+v<=n"
    )
    eligible = {
        r[0]
        for r in db.execute(
            "SELECT a FROM valid WHERE y=2019 GROUP BY a HAVING COUNT(*)=48"
        )
    }
    all_airports = [r[0] for r in db.execute("SELECT DISTINCT a FROM raw ORDER BY a")]
    baseline = {
        a: db.execute("SELECT SUM(n) FROM valid WHERE y=2019 AND a=?", (a,)).fetchone()[
            0
        ]
        for a in eligible
    }
    base_total = sum(baseline.values())
    checks = 0

    def match(actual, expected):
        nonlocal checks
        assert set(actual) == set(expected), (set(actual), set(expected))
        for k, value in expected.items():
            assert str(actual[k]) == str(value), (k, actual[k], value)
            checks += 1

    cohorts = read_csv("results/cohort.csv")
    assert len(cohorts) == len(all_airports)
    for row, a in zip(cohorts, all_airports):
        n = db.execute(
            "SELECT COUNT(*) FROM valid WHERE y=2019 AND a=?", (a,)
        ).fetchone()[0]
        match(
            row,
            dict(
                airport=a,
                eligible=int(a in eligible),
                valid_2019_cells=n,
                required_cells=48,
                reason=(
                    "complete_four_carrier_2019_panel"
                    if a in eligible
                    else "absent_or_unknown_nonpositive_2019_cell"
                ),
            ),
        )
    weights = read_csv("results/weights.csv")
    assert {r["airport"] for r in weights} == eligible
    for r in weights:
        a = r["airport"]
        w = F(baseline[a], base_total)
        match(
            r,
            dict(
                airport=a,
                baseline_reported_count=baseline[a],
                weight_num=w.numerator,
                weight_den=w.denominator,
            ),
        )
    resolutions = read_csv("results/source-resolution.csv")
    assert len(resolutions) == len(cells)
    raw_bykey = {(c, y, m, a): (n, d, k, v) for c, y, m, a, n, d, k, v in cells}
    for r in resolutions:
        c, y, m, a = r["carrier"], int(r["year"]), int(r["month"]), r["airport"]
        n, d, k, v = raw_bykey[c, y, m, a]
        status = (
            "unknown_source_total_or_outcome"
            if any(x is None for x in [n, k, v])
            else (
                "zero_scheduled_total"
                if n == 0
                else "logical_zero_original_null" if d is None else "observed"
            )
        )
        match(r, dict(carrier=c, year=y, month=m, airport=a, resolution=status))
    years = (
        [2019, 2020, 2021, 2022] if args.stage == "development" else [2023, 2024, 2025]
    )
    prefix = "results/" + args.stage + "-"
    expected_panels = {}
    coverage = {}
    expected_counts = {}
    for y in years:
        for c in cfg["carriers"]:
            panel = []
            for a in sorted(eligible):
                n = db.execute(
                    "SELECT COUNT(*) FROM valid WHERE c=? AND y=? AND a=?", (c, y, a)
                ).fetchone()[0]
                expected_panels[c, y, a] = dict(
                    carrier=c,
                    year=y,
                    airport=a,
                    eligible=int(n == 12),
                    valid_months=n,
                    reason=(
                        "complete_positive_source_panel"
                        if n == 12
                        else "absent_unknown_or_nonpositive_source_cell"
                    ),
                )
                if n == 12:
                    panel.append(a)
            covered_total = sum(baseline[a] for a in panel)
            share = F(covered_total, base_total)
            coverage[c, y] = dict(
                carrier=c,
                year=y,
                eligible_airports=len(panel),
                baseline_airports=len(eligible),
                baseline_weight_covered_num=share.numerator,
                baseline_weight_covered_den=share.denominator,
                baseline_weight_covered_decimal=display(share),
            )
            placeholders = ",".join("?" for a in panel)
            for text in cfg["synthetic_conversion_fractions"]:
                q = F(text)
                move = "(d*" + str(q.numerator) + "/" + str(q.denominator) + ")"
                columns = (
                    "SUM(n),SUM(d-"
                    + move
                    + "),SUM(k+"
                    + move
                    + "),SUM(v),SUM(n-d-k-v),SUM(n-k-v-"
                    + move
                    + "),SUM("
                    + move
                    + ")"
                )
                for month_expr, group in [
                    ("CAST(m AS TEXT)", "a,m"),
                    ("'annual'", "a"),
                ]:
                    query = (
                        "SELECT a,"
                        + month_expr
                        + ","
                        + columns
                        + " FROM valid WHERE c=? AND y=? AND a IN ("
                        + placeholders
                        + ") GROUP BY "
                        + group
                    )
                    for a, m, n, d, k, v, o, b, moved in db.execute(
                        query, [c, y, *panel]
                    ):
                        expected_counts[c, y, m, text, a] = dict(
                            carrier=c,
                            year=y,
                            month=m,
                            scenario=text,
                            airport=a,
                            N=n,
                            D=d,
                            C=k,
                            V=v,
                            O=o,
                            B=b,
                            moved=moved,
                        )
    rows = read_csv(prefix + "panel-airports.csv")
    assert len(rows) == len(expected_panels)
    for r in rows:
        match(r, expected_panels[r["carrier"], int(r["year"]), r["airport"]])
    rows = read_csv(prefix + "coverage.csv")
    assert len(rows) == len(coverage)
    for r in rows:
        match(r, coverage[r["carrier"], int(r["year"])])
    actual = read_csv(prefix + "airport-counts.csv.gz")
    assert len(actual) == len(expected_counts)
    seen = set()
    grouped = defaultdict(dict)
    for r in actual:
        key = (r["carrier"], int(r["year"]), r["month"], r["scenario"], r["airport"])
        assert key not in seen
        seen.add(key)
        expected = expected_counts[key]
        match(r, expected)
        grouped[key[:4]][key[4]] = expected
    assert seen == set(expected_counts)

    def direct(row):
        n, d, k, v, o, b = (row[x] for x in ["N", "D", "C", "V", "O", "B"])
        return dict(
            completed_delay=F(d, b) if b else None,
            scheduled_disruption=F(d + k + v, n),
            completed_ontime=F(o, b) if b else None,
            scheduled_ontime=F(o, n),
            cancellation=F(k, n),
            diversion=F(v, n),
            denominator_inflation=F(o, b) - F(o, n) if b else None,
        )

    expected_metrics = {}
    identity_checks = 0
    for (c, y, m, text), group in grouped.items():
        pooled = direct(
            {
                x: sum(r[x] for r in group.values())
                for x in ["N", "D", "C", "V", "O", "B"]
            }
        )
        airport_values = {a: direct(row) for a, row in group.items()}
        total = sum(baseline[a] for a in group)
        standardized = {
            metric: (
                None
                if any(v[metric] is None for v in airport_values.values())
                else sum(
                    (F(baseline[a], total) * airport_values[a][metric] for a in group),
                    F(0),
                )
            )
            for metric in pooled
        }
        for view, values in [
            ("observed_pooled", pooled),
            ("airport_standardized", standardized),
        ]:
            for metric, value in values.items():
                expected_metrics[c, y, m, text, view, metric] = dict(
                    carrier=c,
                    year=y,
                    month=m,
                    scenario=text,
                    view=view,
                    metric=metric,
                    defined=int(value is not None),
                    numerator="" if value is None else value.numerator,
                    denominator="" if value is None else value.denominator,
                    value=display(value),
                    reason=(
                        "zero_completed_denominator_in_weighted_population"
                        if value is None
                        else ""
                    ),
                )
        if text != "0":
            original = grouped[c, y, m, "0"]
            for a, row in group.items():
                before = original[a]
                assert (
                    row["N"] == before["N"]
                    and row["O"] == before["O"]
                    and row["V"] == before["V"]
                )
                assert row["D"] + row["C"] == before["D"] + before["C"]
                identity_checks += 4
                if before["B"] and row["B"]:
                    assert F(row["O"], row["B"]) >= F(before["O"], before["B"])
                    identity_checks += 1
    rows = read_csv(prefix + "metrics.csv.gz")
    assert len(rows) == len(expected_metrics)
    seen = set()
    for r in rows:
        key = (
            r["carrier"],
            int(r["year"]),
            r["month"],
            r["scenario"],
            r["view"],
            r["metric"],
        )
        assert key not in seen
        seen.add(key)
        match(r, expected_metrics[key])
    assert seen == set(expected_metrics)
    summary = json.loads((ROOT / (prefix + "SUMMARY.json")).read_text(encoding="utf-8"))
    assert (
        summary["carrier_year_panels"] == len(coverage)
        and summary["baseline_airports"] == len(eligible)
        and summary["airport_count_rows"] == len(expected_counts)
        and summary["metric_rows"] == len(expected_metrics)
        and summary["undefined_metric_rows"]
        == sum(r["defined"] == 0 for r in expected_metrics.values())
    )
    checks += 5
    receipt = dict(
        status="PASS",
        stage=args.stage,
        exact_exported_fields_checked=checks,
        conversion_identity_checks=identity_checks,
        airport_count_rows=len(expected_counts),
        metric_rows=len(expected_metrics),
        baseline_airports=len(eligible),
        independence="Separate SQLite cohort/weights/count aggregation and rational partition reconstruction; imports no analysis/model helper.",
        scope="Finite captured source cells and declared synthetic transformations only; no source truth, causal or future guarantee.",
    )
    (ROOT / (prefix + "VERIFICATION.json")).write_bytes(
        (json.dumps(receipt, indent=2) + "\n").encode()
    )
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
