"""Run the fixed finite descriptive comparison on the captured source projection."""

import argparse
from collections import defaultdict
import csv
from decimal import Decimal, localcontext
from fractions import Fraction
import gzip
import hashlib
import io
import json
from pathlib import Path

from model import METRICS, convert, metrics, resolve, standardize

ROOT = Path(__file__).resolve().parents[1]


def write_csv(name, rows, fields):
    out = io.StringIO(newline="")
    w = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    data = out.getvalue().encode()
    (ROOT / name).write_bytes(
        gzip.compress(data, mtime=0) if name.endswith(".gz") else data
    )


def decimal(value):
    if value is None:
        return ""
    with localcontext() as context:
        context.prec = max(
            60, len(str(value.numerator)) + len(str(value.denominator)) + 10
        )
        return format(
            (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
                Decimal("0.000000000000000001")
            ),
            "f",
        )


def load_source():
    manifest = json.loads(
        (ROOT / "data/source/manifest.json").read_text(encoding="utf-8")
    )
    data = gzip.decompress((ROOT / manifest["projection_file"]).read_bytes())
    assert hashlib.sha256(data).hexdigest() == manifest["projection_csv_sha256"]
    rows = {}
    resolutions = []
    for r in csv.DictReader(io.StringIO(data.decode())):
        y, m = int(r["year"]), int(r["month"])
        carrier, airport = r["carrier"], r["airport"]
        values = {
            name: int(r[source]) if r[source] else None
            for name, source in [
                ("N", "arr_flights"),
                ("D", "arr_del15"),
                ("C", "arr_cancelled"),
                ("V", "arr_diverted"),
            ]
        }
        got, status = resolve(values)
        key = (carrier, y, m, airport)
        assert key not in rows
        rows[key] = got
        resolutions.append(
            dict(carrier=carrier, year=y, month=m, airport=airport, resolution=status)
        )
    return rows, resolutions


def cohort(source, cfg):
    airports = sorted({k[3] for k in source})
    records = []
    eligible = []
    for airport in airports:
        valid = sum(
            source.get((c, 2019, m, airport)) is not None
            for c in cfg["carriers"]
            for m in range(1, 13)
        )
        ok = valid == 48
        records.append(
            dict(
                airport=airport,
                eligible=int(ok),
                valid_2019_cells=valid,
                required_cells=48,
                reason=(
                    "complete_four_carrier_2019_panel"
                    if ok
                    else "absent_or_unknown_nonpositive_2019_cell"
                ),
            )
        )
        if ok:
            eligible.append(airport)
    assert len(eligible) >= 5
    baseline = {
        a: sum(
            source[c, 2019, m, a]["N"] for c in cfg["carriers"] for m in range(1, 13)
        )
        for a in eligible
    }
    total = sum(baseline.values())
    weights = {a: Fraction(baseline[a], total) for a in eligible}
    return records, eligible, baseline, weights


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["development", "held"])
    args = ap.parse_args()
    cfg = json.loads((ROOT / "protocol.json").read_text(encoding="utf-8"))
    if args.stage == "held":
        from verify_freeze import verify

        verify()
    source, resolutions = load_source()
    cohort_rows, initial, baseline, base_weights = cohort(source, cfg)
    if args.stage == "development":
        write_csv(
            "results/source-resolution.csv",
            resolutions,
            ["carrier", "year", "month", "airport", "resolution"],
        )
        write_csv(
            "results/cohort.csv",
            cohort_rows,
            ["airport", "eligible", "valid_2019_cells", "required_cells", "reason"],
        )
        write_csv(
            "results/weights.csv",
            [
                dict(
                    airport=a,
                    baseline_reported_count=baseline[a],
                    weight_num=base_weights[a].numerator,
                    weight_den=base_weights[a].denominator,
                )
                for a in initial
            ],
            ["airport", "baseline_reported_count", "weight_num", "weight_den"],
        )
    years = (
        [2019, 2020, 2021, 2022] if args.stage == "development" else cfg["held_years"]
    )
    panel_rows = []
    coverage = []
    count_rows = []
    metric_rows = []
    for year in years:
        for carrier in cfg["carriers"]:
            panel = []
            for airport in initial:
                valid = sum(
                    source.get((carrier, year, m, airport)) is not None
                    for m in range(1, 13)
                )
                ok = valid == 12
                panel_rows.append(
                    dict(
                        carrier=carrier,
                        year=year,
                        airport=airport,
                        eligible=int(ok),
                        valid_months=valid,
                        reason=(
                            "complete_positive_source_panel"
                            if ok
                            else "absent_unknown_or_nonpositive_source_cell"
                        ),
                    )
                )
                if ok:
                    panel.append(airport)
            assert (
                panel
            ), "No complete airport panel; retain failure instead of inventing rates"
            covered = sum((base_weights[a] for a in panel), Fraction(0))
            weights = {a: base_weights[a] / covered for a in panel}
            coverage.append(
                dict(
                    carrier=carrier,
                    year=year,
                    eligible_airports=len(panel),
                    baseline_airports=len(initial),
                    baseline_weight_covered_num=covered.numerator,
                    baseline_weight_covered_den=covered.denominator,
                    baseline_weight_covered_decimal=decimal(covered),
                )
            )
            for qtext in cfg["synthetic_conversion_fractions"]:
                q = Fraction(qtext)
                annual = {a: dict(N=0, D=0, C=0, V=0, moved=0) for a in panel}
                for month in range(1, 13):
                    current = {}
                    for airport in panel:
                        value, moved = convert(source[carrier, year, month, airport], q)
                        current[airport] = value
                        for k in ["N", "D", "C", "V"]:
                            annual[airport][k] += value[k]
                        annual[airport]["moved"] += moved
                        count_rows.append(
                            dict(
                                carrier=carrier,
                                year=year,
                                month=str(month),
                                scenario=qtext,
                                airport=airport,
                                **value,
                                O=value["N"] - value["D"] - value["C"] - value["V"],
                                B=value["N"] - value["C"] - value["V"],
                                moved=moved
                            )
                        )
                    append_metrics(
                        metric_rows, carrier, year, str(month), qtext, current, weights
                    )
                for airport, row in annual.items():
                    moved = row.pop("moved")
                    count_rows.append(
                        dict(
                            carrier=carrier,
                            year=year,
                            month="annual",
                            scenario=qtext,
                            airport=airport,
                            **row,
                            O=row["N"] - row["D"] - row["C"] - row["V"],
                            B=row["N"] - row["C"] - row["V"],
                            moved=moved
                        )
                    )
                append_metrics(
                    metric_rows, carrier, year, "annual", qtext, annual, weights
                )
    prefix = "results/" + args.stage + "-"
    write_csv(
        prefix + "panel-airports.csv",
        panel_rows,
        ["carrier", "year", "airport", "eligible", "valid_months", "reason"],
    )
    write_csv(
        prefix + "coverage.csv",
        coverage,
        [
            "carrier",
            "year",
            "eligible_airports",
            "baseline_airports",
            "baseline_weight_covered_num",
            "baseline_weight_covered_den",
            "baseline_weight_covered_decimal",
        ],
    )
    write_csv(
        prefix + "airport-counts.csv.gz",
        count_rows,
        [
            "carrier",
            "year",
            "month",
            "scenario",
            "airport",
            "N",
            "D",
            "C",
            "V",
            "O",
            "B",
            "moved",
        ],
    )
    write_csv(
        prefix + "metrics.csv.gz",
        metric_rows,
        [
            "carrier",
            "year",
            "month",
            "scenario",
            "view",
            "metric",
            "defined",
            "numerator",
            "denominator",
            "value",
            "reason",
        ],
    )
    summary = dict(
        stage=args.stage,
        carrier_year_panels=len(coverage),
        baseline_airports=len(initial),
        airport_count_rows=len(count_rows),
        metric_rows=len(metric_rows),
        undefined_metric_rows=sum(not r["defined"] for r in metric_rows),
        scenarios=cfg["synthetic_conversion_fractions"],
        interpretation=cfg["scope"],
    )
    (ROOT / (prefix + "SUMMARY.json")).write_bytes(
        (json.dumps(summary, indent=2) + "\n").encode()
    )
    print(json.dumps(summary))


def append_metrics(output, carrier, year, month, scenario, values, weights):
    pooled = metrics(
        {k: sum(v[k] for v in values.values()) for k in ["N", "D", "C", "V"]}
    )
    standardized = standardize(values, weights)
    for view, got in [
        ("observed_pooled", pooled),
        ("airport_standardized", standardized),
    ]:
        for metric in METRICS:
            value = got[metric]
            output.append(
                dict(
                    carrier=carrier,
                    year=year,
                    month=month,
                    scenario=scenario,
                    view=view,
                    metric=metric,
                    defined=int(value is not None),
                    numerator="" if value is None else value.numerator,
                    denominator="" if value is None else value.denominator,
                    value=decimal(value),
                    reason=(
                        "zero_completed_denominator_in_weighted_population"
                        if value is None
                        else ""
                    ),
                )
            )


if __name__ == "__main__":
    main()
