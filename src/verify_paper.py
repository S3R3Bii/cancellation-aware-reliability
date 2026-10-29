"""Recompute displayed tables, source totals, qualifications and bounded PDF actions."""

import csv, gzip, hashlib, io, json, re
import unicodedata
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from fractions import Fraction as F
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


def csvrows(name):
    data = (ROOT / name).read_bytes()
    if name.endswith(".gz"):
        data = gzip.decompress(data)
    return list(csv.DictReader(io.StringIO(data.decode())))


def rounded(q):
    q = F(q)
    with localcontext() as c:
        c.prec = len(str(q.numerator)) + len(str(q.denominator)) + 80
        return format(
            (Decimal(q.numerator) / Decimal(q.denominator)).quantize(
                Decimal(".001"), rounding=ROUND_HALF_EVEN
            ),
            ",.3f",
        )


def main():
    records = {}
    for stage in ["development", "held"]:
        for row in csvrows("results/" + stage + "-metrics.csv.gz"):
            if row["month"] == "annual":
                records[
                    row["carrier"],
                    int(row["year"]),
                    row["scenario"],
                    row["view"],
                    row["metric"],
                ] = (
                    F(int(row["numerator"]), int(row["denominator"]))
                    if row["defined"] == "1"
                    else None
                )
    coverage = {
        (r["carrier"], int(r["year"])): r
        for s in ["development", "held"]
        for r in csvrows("results/" + s + "-coverage.csv")
    }
    cells = csvrows("data/source/flight-counts.csv.gz")
    primary = [(c, y) for y in [2023, 2024, 2025] for c in ["UA", "WN"]]
    cases = [(c, y) for y in [2023, 2024, 2025] for c in ["AA", "DL", "UA", "WN"]]
    baseline = {
        r["airport"] for r in csvrows("results/cohort.csv") if r["eligible"] == "1"
    }
    computed = dict(primary=[], mix=[], synthetic=[], development=[])
    for c, y in primary:
        # Independent source projection sum, not the analysis count-export total.
        total = sum(
            int(r["arr_flights"])
            for r in cells
            if r["carrier"] == c
            and int(r["year"]) == y
            and r["airport"] in baseline
            and r["arr_flights"]
        )
        computed["primary"].append(
            [
                c,
                y,
                format(total, ","),
                *[
                    rounded(records[c, y, "0", "airport_standardized", m] * 100)
                    for m in [
                        "completed_ontime",
                        "scheduled_ontime",
                        "denominator_inflation",
                        "cancellation",
                        "diversion",
                    ]
                ],
            ]
        )
    for c, y in cases:
        cov = coverage[c, y]
        fixed = records[c, y, "0", "airport_standardized", "scheduled_ontime"]
        pooled = records[c, y, "0", "observed_pooled", "scheduled_ontime"]
        computed["mix"].append(
            [
                c,
                y,
                cov["eligible_airports"],
                rounded(
                    F(
                        int(cov["baseline_weight_covered_num"]),
                        int(cov["baseline_weight_covered_den"]),
                    )
                    * 100
                ),
                rounded(pooled * 100),
                rounded(fixed * 100),
                rounded((pooled - fixed) * 100),
            ]
        )
        computed["synthetic"].append(
            [
                c,
                y,
                *[
                    rounded(
                        (
                            records[c, y, q, "airport_standardized", "completed_ontime"]
                            - records[
                                c, y, "0", "airport_standardized", "completed_ontime"
                            ]
                        )
                        * 100
                    )
                    for q in ["1/10", "1/4", "1/2"]
                ],
                rounded(
                    (
                        records[c, y, "1/2", "airport_standardized", "scheduled_ontime"]
                        - fixed
                    )
                    * 100
                ),
            ]
        )
    for y in [2019, 2020, 2021, 2022]:
        for c in ["AA", "DL", "UA", "WN"]:
            cov = coverage[c, y]
            computed["development"].append(
                [
                    c,
                    y,
                    cov["eligible_airports"],
                    rounded(
                        F(
                            int(cov["baseline_weight_covered_num"]),
                            int(cov["baseline_weight_covered_den"]),
                        )
                        * 100
                    ),
                    *[
                        rounded(records[c, y, "0", "airport_standardized", m] * 100)
                        for m in [
                            "completed_ontime",
                            "scheduled_ontime",
                            "denominator_inflation",
                        ]
                    ],
                ]
            )
    tex = (ROOT / "paper/main.tex").read_text(encoding="utf-8")
    assert (
        "\\iffalse" not in tex and "\\input" not in tex and "\\includeonly" not in tex
    )
    reader = PdfReader(ROOT / "paper/manuscript.pdf")
    assert not reader.is_encrypted and len(reader.pages) == 7
    text = " ".join(page.extract_text() for page in reader.pages)
    checks = 4
    table_values = json.loads(
        (ROOT / "paper/TABLE_VALUES.json").read_text(encoding="utf-8")
    )
    for name, rows in computed.items():
        assert table_values[name] == rows, name
        checks += 1
        for row in rows:
            line = (
                " & ".join(str(v).replace("%", r"\%") for v in row) + " " + chr(92) * 2
            )
            assert line in tex, (name, line)
            checks += 1
            for value in row:
                if re.fullmatch(r"[0-9][0-9,.]*", str(value)):
                    assert str(value) in text, (name, value)
                    checks += 1
    gap = [
        records[c, y, "0", "airport_standardized", "denominator_inflation"] * 100
        for c, y in primary
    ]
    assert rounded(min(gap)) + "--" + rounded(max(gap)) + " percentage points" in tex
    checks += 1
    source = json.loads(
        (ROOT / "data/source/manifest.json").read_text(encoding="utf-8")
    )
    for number in [
        source["quality"]["source_rows"],
        source["quality"]["selected_rows"],
        source["independent_parser_scalar_checks"],
        source["source_zip_bytes"],
    ]:
        assert format(number, ",") in tex and format(number, ",") in text
        checks += 2
    for phrase in [
        "official BTS tabular on-time percentage already uses scheduled totals",
        "not independently verified operating-only or disjoint populations",
        "No causal airline strategy",
        "Original blanks remain blank",
        "no fitting, model selection, optimizer or survival model",
        "a mathematical identity, not a newly discovered causal effect",
        "complete schedule coverage and source truth remain unknown",
        "conditional B=0 rates stay undefined",
    ]:
        assert phrase in tex, phrase
        checks += 1
    # TeX ligatures and line-end hyphenation are presentation, not missing claims.
    compact = lambda s: re.sub(
        "[^a-z0-9]", "", unicodedata.normalize("NFKC", s).lower()
    )
    normalized = compact(text)
    for phrase in [
        "The official BTS tabular on-time percentage already uses scheduled totals",
        "Original blanks remain blank",
        "not a newly discovered causal effect",
        "not independently verified operating-only or disjoint populations",
    ]:
        assert compact(phrase) in normalized, phrase
        checks += 1
    dev = json.loads((ROOT / "results/development-VERIFICATION.json").read_text())
    held = json.loads((ROOT / "results/held-VERIFICATION.json").read_text())
    replay = json.loads((ROOT / "REPROCHECK.json").read_text())
    for count in [
        dev["exact_exported_fields_checked"],
        dev["conversion_identity_checks"],
        held["exact_exported_fields_checked"],
        held["conversion_identity_checks"],
        replay["exact_csv_fields"],
    ]:
        assert format(count, ",") in tex and format(count, ",") in text
        checks += 2
    scope = json.loads(
        (ROOT / "paper/PUBLICATION_SCOPE.json").read_text(encoding="utf-8")
    )
    assert (
        scope["scope"] == "independent-program-study"
        and scope["formal_submission_target"] is False
        and len(scope["public_files"]) == 5
    )
    checks += 1
    for name, digest in scope["public_files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
        checks += 1
    for name in ["denominator_rates", "airport_mix", "synthetic_conversion"]:
        assert (ROOT / "paper/images" / (name + ".pdf")).read_bytes() == (
            ROOT / "figures" / (name + ".pdf")
        ).read_bytes()
        checks += 1
    action_checks = 0
    for path in [ROOT / "paper/manuscript.pdf", *(ROOT / "paper/images").glob("*.pdf")]:
        doc = PdfReader(path)
        catalog = doc.trailer["/Root"]
        assert not any(k in catalog for k in ["/AA", "/AcroForm"])
        opening = catalog.get("/OpenAction")
        if opening is not None:
            assert (
                isinstance(opening, list)
                and len(opening) == 2
                and str(opening[1]) == "/Fit"
            )
            assert opening[0].get_object().get("/Type") == "/Page"
        names = catalog.get("/Names", {})
        if hasattr(names, "get_object"):
            names = names.get_object()
        assert "/JavaScript" not in names and "/EmbeddedFiles" not in names
        for page in doc.pages:
            assert "/AA" not in page
            for ref in page.get("/Annots", []):
                annotation = ref.get_object()
                assert annotation.get("/Subtype") == "/Link"
                assert "/AA" not in annotation
                if "/A" in annotation:
                    assert annotation["/A"].get("/S") == "/URI"
                if "/Rect" in annotation:
                    x0, y0, x1, y1 = map(float, annotation["/Rect"])
                    assert (
                        0 <= x0 <= x1 <= float(page.mediabox.right) + 0.5
                        and 0 <= y0 <= y1 <= float(page.mediabox.top) + 0.5
                    )
        action_checks += 1
    assert not re.search(
        r"[Cc]:\\[Uu]sers\\|/[Uu]sers/|/[Hh]ome/", text + str(reader.metadata)
    )
    checks += 1
    receipt = dict(
        status="PASS",
        independent_paper_checks=checks,
        primary_rows=6,
        held_mix_rows=12,
        synthetic_rows=12,
        development_rows=16,
        pdf_pages=7,
        pdf_active_content_checks=action_checks,
        scope="Independent display reconstruction, direct primary source-count sums, qualifications, exact approved hashes and bounded PDF actions. Rendered layout and source rights reviewed separately.",
    )
    (ROOT / "paper/VERIFICATION.json").write_bytes(
        (json.dumps(receipt, indent=2) + "\n").encode()
    )
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
