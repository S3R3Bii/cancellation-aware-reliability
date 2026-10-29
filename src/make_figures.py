"""Three original figures; retain actual artist data for independent checking."""

import csv, gzip, hashlib, io, json
from fractions import Fraction
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "pdf.fonttype": 42,
        "svg.fonttype": "none",
        "savefig.facecolor": "white",
    }
)


def main():
    records = list(
        csv.DictReader(
            io.StringIO(
                gzip.decompress(
                    (ROOT / "results/held-metrics.csv.gz").read_bytes()
                ).decode()
            )
        )
    )
    values = {
        (
            r["carrier"],
            int(r["year"]),
            r["month"],
            r["scenario"],
            r["view"],
            r["metric"],
        ): (
            Fraction(int(r["numerator"]), int(r["denominator"]))
            if r["defined"] == "1"
            else None
        )
        for r in records
    }
    primary = [(c, y) for y in [2023, 2024, 2025] for c in ["UA", "WN"]]
    all_cases = [(c, y) for y in [2023, 2024, 2025] for c in ["AA", "DL", "UA", "WN"]]
    artists = {}
    hashes = {}

    def metric(c, y, scenario, view, name):
        return float(values[c, y, "annual", scenario, view, name]) * 100

    def save(fig, name):
        for extension in ["pdf", "svg", "png"]:
            path = ROOT / "figures" / (name + "." + extension)
            fig.savefig(
                path,
                dpi=180,
                metadata={"Creator": "Original independent research figure"},
            )
            if extension == "svg":
                path.write_bytes(
                    (
                        "\n".join(
                            line.rstrip()
                            for line in path.read_text(encoding="utf-8").splitlines()
                        )
                        + "\n"
                    ).encode("utf-8")
                )
            hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    fig.subplots_adjust(left=0.15, right=0.87, top=0.78, bottom=0.20)
    y = np.arange(6)
    scheduled = np.array(
        [
            metric(c, yr, "0", "airport_standardized", "scheduled_ontime")
            for c, yr in primary
        ]
    )
    completed = np.array(
        [
            metric(c, yr, "0", "airport_standardized", "completed_ontime")
            for c, yr in primary
        ]
    )
    segments = ax.hlines(y, scheduled, completed, color="#bbc7cf", linewidth=4)
    p1 = ax.scatter(
        scheduled,
        y,
        s=55,
        color="#006d77",
        label="All reported scheduled flights",
        zorder=3,
    )
    p2 = ax.scatter(
        completed,
        y,
        s=55,
        color="#bd3b27",
        marker="D",
        label="Completed-at-destination flights",
        zorder=3,
    )
    for i, (s, c) in enumerate(zip(scheduled, completed)):
        ax.text(79.35, i, f"+{c-s:.2f} pp", va="center", fontsize=9)
    ax.set_yticks(y, [f"{c}  {yr}" for c, yr in primary])
    ax.invert_yaxis()
    ax.set_xlim(74.8, 80.3)
    ax.set_xticks([75, 76, 77, 78, 79])
    ax.grid(axis="x", alpha=0.18)
    ax.set_axisbelow(True)
    ax.set_xlabel(
        "On-time flights (%) · fixed 2019 airport weights · point axis shown 74.8–80.3%"
    )
    fig.suptitle(
        "The denominator changes the displayed on-time rate",
        x=0.08,
        ha="left",
        y=0.97,
        fontsize=15,
        fontweight="bold",
    )
    fig.text(
        0.08,
        0.875,
        "Primary held panels: six UA/WN carrier-years, 2023–2025",
        fontsize=10,
        color="#354c5c",
    )
    ax.legend(
        loc="lower left",
        bbox_to_anchor=(-0.1, 1.025),
        frameon=False,
        ncol=2,
        fontsize=8.5,
    )
    fig.text(
        0.08,
        0.025,
        "The official BTS source uses scheduled totals; the completed-flight view is constructed here.\nCancelled and diverted flights are excluded only from the constructed denominator.\nNominal carrier cells; no passenger-delay, causal or verified operating-only claim.",
        fontsize=8.5,
        color="#354c5c",
    )
    artists["denominator_rates"] = dict(
        cases=[f"{c}-{yr}" for c, yr in primary],
        scheduled_offsets=p1.get_offsets().tolist(),
        completed_offsets=p2.get_offsets().tolist(),
        segments=[x.tolist() for x in segments.get_segments()],
        gap_annotations=[t.get_text() for t in ax.texts],
    )
    save(fig, "denominator_rates")

    fig, ax = plt.subplots(figsize=(8.6, 6.0))
    fig.subplots_adjust(left=0.15, right=0.96, top=0.78, bottom=0.16)
    y = np.arange(12)
    pooled = np.array(
        [
            metric(c, yr, "0", "observed_pooled", "scheduled_ontime")
            for c, yr in all_cases
        ]
    )
    standardized = np.array(
        [
            metric(c, yr, "0", "airport_standardized", "scheduled_ontime")
            for c, yr in all_cases
        ]
    )
    line = ax.hlines(y, standardized, pooled, color="#b9c9d5", linewidth=3)
    p1 = ax.scatter(
        pooled, y, s=35, color="#5367a6", label="Observed count mix", zorder=3
    )
    p2 = ax.scatter(
        standardized,
        y,
        s=35,
        color="#006d77",
        marker="s",
        label="Fixed 2019 airport mix",
        zorder=3,
    )
    ax.set_yticks(y, [f"{c}  {yr}" for c, yr in all_cases])
    ax.invert_yaxis()
    ax.set_xlim(68, 86)
    ax.set_xticks([70, 75, 80, 85])
    ax.grid(axis="x", alpha=0.18)
    ax.set_axisbelow(True)
    ax.set_xlabel("Scheduled-flight on-time rate (%) · point axis shown 68–86%")
    ax.legend(
        loc="lower left",
        bbox_to_anchor=(-0.08, 1.02),
        frameon=False,
        ncol=2,
        fontsize=9,
    )
    fig.suptitle(
        "Airport mix also changes a reported percentage",
        x=0.08,
        ha="left",
        y=0.97,
        fontsize=15,
        fontweight="bold",
    )
    fig.text(
        0.08,
        0.89,
        "All twelve held carrier-years; AA/DL are prespecified secondary descriptions",
        fontsize=10,
        color="#354c5c",
    )
    fig.text(
        0.08,
        0.035,
        "The reference weights control this recorded airport mix only, not routes, season, weather or passengers.\nAA 2025 uses 57/58 baseline airports (99.862% reference weight); other held panels use all 58.",
        fontsize=8.5,
        color="#354c5c",
    )
    artists["airport_mix"] = dict(
        cases=[f"{c}-{yr}" for c, yr in all_cases],
        pooled_offsets=p1.get_offsets().tolist(),
        standardized_offsets=p2.get_offsets().tolist(),
        segments=[x.tolist() for x in line.get_segments()],
    )
    save(fig, "airport_mix")

    scenarios = ["0", "1/10", "1/4", "1/2"]
    matrix = np.array(
        [
            [
                metric(c, yr, q, "airport_standardized", "completed_ontime")
                - metric(c, yr, "0", "airport_standardized", "completed_ontime")
                for q in scenarios
            ]
            for c, yr in primary
        ]
    )
    fig, ax = plt.subplots(figsize=(8.6, 4.9))
    fig.subplots_adjust(left=0.15, right=0.88, top=0.76, bottom=0.20)
    im = ax.imshow(matrix, cmap="Blues", vmin=0, vmax=12, aspect="auto")
    ax.set_yticks(range(6), [f"{c}  {yr}" for c, yr in primary])
    ax.set_xticks(range(4), ["0%", "10%", "25%", "50%"])
    ax.set_xlabel(
        "Synthetic share of delayed flights converted to cancellations in each monthly cell"
    )
    annotations = []
    for row in range(6):
        for col in range(4):
            rgba = im.cmap(im.norm(matrix[row, col]))
            linear = [
                x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
                for x in rgba[:3]
            ]
            lum = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
            black = (lum + 0.05) / 0.05
            white = 1.05 / (lum + 0.05)
            color = "black" if black >= white else "white"
            text = ax.text(
                col,
                row,
                f"{matrix[row,col]:.2f}",
                ha="center",
                va="center",
                color=color,
                fontsize=10,
            )
            annotations.append(
                dict(
                    row=row,
                    col=col,
                    text=text.get_text(),
                    color=color,
                    background=list(rgba),
                    contrast=max(black, white),
                )
            )
    cb = fig.colorbar(im, ax=ax, pad=0.03, fraction=0.035)
    cb.set_label("Completed-flight rate increase (percentage points)", fontsize=9)
    fig.suptitle(
        "A synthetic cancellation can improve the conditional metric",
        x=0.08,
        ha="left",
        y=0.97,
        fontsize=15,
        fontweight="bold",
    )
    fig.text(
        0.08,
        0.87,
        "The scheduled-flight on-time rate stays exactly unchanged in every conversion case",
        fontsize=10,
        color="#354c5c",
    )
    fig.text(
        0.08,
        0.035,
        "Original N and on-time count O are held fixed; floor(q × D) delayed counts move to cancelled counts.\nThis is a mechanical denominator test, not evidence of actual airline actions or passenger benefit.",
        fontsize=8.5,
        color="#354c5c",
    )
    artists["synthetic_conversion"] = dict(
        cases=[f"{c}-{yr}" for c, yr in primary],
        scenarios=scenarios,
        matrix=im.get_array().tolist(),
        annotations=annotations,
    )
    save(fig, "synthetic_conversion")
    (ROOT / "figures/ARTIST_VALUES.json").write_bytes(
        (json.dumps(artists, indent=2) + "\n").encode()
    )
    (ROOT / "figures/MANIFEST.json").write_bytes(
        (json.dumps(hashes, indent=2) + "\n").encode()
    )
    print(json.dumps(dict(figures=3, exports=len(hashes))))


if __name__ == "__main__":
    main()
