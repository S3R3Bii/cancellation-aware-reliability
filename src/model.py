"""Exact descriptive count metrics; no fitting or predictive model is used."""

from fractions import Fraction

METRICS = [
    "completed_delay",
    "scheduled_disruption",
    "completed_ontime",
    "scheduled_ontime",
    "cancellation",
    "diversion",
    "denominator_inflation",
]


def resolve(source):
    values = {k: source[k] for k in ["N", "D", "C", "V"]}
    if any(values[k] is None for k in ["N", "C", "V"]):
        return None, "unknown_source_total_or_outcome"
    if any(not isinstance(v, int) or v < 0 for v in values.values() if v is not None):
        raise ValueError("Counts must be nonnegative integers")
    if values["N"] == 0:
        return None, "zero_scheduled_total"
    status = "observed"
    if values["D"] is None:
        if values["N"] == values["C"] + values["V"]:
            values["D"] = 0
            status = "logical_zero_original_null"
        else:
            raise ValueError("Unknown delay with positive remaining denominator")
    if values["D"] + values["C"] + values["V"] > values["N"]:
        raise ValueError("Outcomes exceed total")
    return values, status


def convert(row, fraction):
    if not Fraction(0) <= fraction <= Fraction(1):
        raise ValueError("Conversion fraction outside unit interval")
    result = dict(row)
    moved = (row["D"] * fraction.numerator) // fraction.denominator
    result["D"] -= moved
    result["C"] += moved
    return result, moved


def metrics(row):
    n, d, c, v = (row[k] for k in ["N", "D", "C", "V"])
    if (
        not all(isinstance(x, int) and x >= 0 for x in [n, d, c, v])
        or d + c + v > n
        or n == 0
    ):
        raise ValueError("Invalid partition")
    b = n - c - v
    o = b - d
    completed_delay = Fraction(d, b) if b else None
    completed_ontime = Fraction(o, b) if b else None
    scheduled_ontime = Fraction(o, n)
    return dict(
        completed_delay=completed_delay,
        scheduled_disruption=Fraction(d + c + v, n),
        completed_ontime=completed_ontime,
        scheduled_ontime=scheduled_ontime,
        cancellation=Fraction(c, n),
        diversion=Fraction(v, n),
        denominator_inflation=completed_ontime - scheduled_ontime if b else None,
    )


def standardize(rows, weights):
    if not rows or set(rows) != set(weights) or sum(weights.values()) != 1:
        raise ValueError("Weights must cover exactly the panel and sum to one")
    values = {k: metrics(r) for k, r in rows.items()}
    # Undefined conditional cells stay undefined; silently dropping their weights
    # would compare a different airport population with the scheduled metric.
    return {
        m: (
            None
            if any(values[k][m] is None for k in rows)
            else sum((weights[k] * values[k][m] for k in rows), Fraction(0))
        )
        for m in METRICS
    }
