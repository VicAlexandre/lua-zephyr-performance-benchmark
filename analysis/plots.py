"""Figures: footprint (CSVs from data/results) and histograms (raw data).

Usage:
    python analysis/plots.py [--results data/results/zbook] [--raw data/raw/zbook] [--out figures]
"""

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, NullFormatter

sys.path.insert(0, str(Path(__file__).parent))
from analyze import load_config, metrics

RAM_TOTAL_KB = 520
DEADLINE_MS = 100

COLORS = {"BASE": "#7f7f7f", "MT": "#1f5fa8", "MTEQ": "#1f5fa8", "MTSPLIT": "#5aa05a",
          "MC": "#d07a1f"}
LABELS = {"BASE": "C baseline", "MT": "MT", "MC": "MC", "MTEQ": "MT, equal priorities",
          "MTSPLIT": "MT, prioritized"}
MARKERS = {"BASE": "s", "MT": "o", "MTEQ": "o", "MTSPLIT": "^", "MC": "D"}
B_MODELS = ("BASE", "MT", "MC")
C_MODELS = ("MC", "MTEQ", "MTSPLIT")

plt.rcParams.update({
    "font.family": "STIXGeneral",
    "mathtext.fontset": "stix",
    "font.size": 12,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": "#dddddd",
    "grid.linewidth": 0.6,
    "legend.frameon": False,
    "figure.figsize": (6.3, 5.0),
    "savefig.bbox": "tight",
})


def num(v: float) -> str:
    """Number with comma thousands separators, without trailing zeros."""
    return f"{v:,.2f}".rstrip("0").rstrip(".")

FMT = FuncFormatter(lambda v, _: num(v))


def read(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def fig_a_ram(res: Path, out: Path) -> None:
    rows = read(res / "A_footprint.csv")
    fits = {r["model"]: r for r in read(res / "A_fit.csv")}
    ref_kb = next((int(r["ram_reserved"]) - int(r["ram_lua"])) / 1024
                  for r in rows if r["fits"] == "1")

    fig, ax = plt.subplots()
    for model in ("MT", "MC"):
        pts = sorted((int(r["n"]), int(r["ram_reserved"]) / 1024) for r in rows
                     if r["model"] == model and r["fits"] == "1" and r["n"].isdigit())
        n, kb = zip(*pts)
        ax.plot(n, kb, MARKERS[model], color=COLORS[model], label=LABELS[model])
        f = fits[model]
        a, b = float(f["a_bytes"]) / 1024, float(f["b_bytes_per_task"]) / 1024
        xs = [1, min(31, (RAM_TOTAL_KB * 1.1 - ref_kb - a) / b)]
        ax.plot(xs, [ref_kb + a + b * x for x in xs], "-", lw=1, color=COLORS[model], alpha=0.6)
        ax.annotate(f"{num(round(b, 1))} KB/task", (xs[-1], ref_kb + a + b * xs[-1]),
                    xytext=(-6, 4), textcoords="offset points", ha="right", color=COLORS[model])
    for r in rows:
        if r["fits"] != "1" and r["n"].isdigit():
            ax.plot(int(r["n"]), RAM_TOTAL_KB, "x", color=COLORS[r["model"]], ms=8, mew=2)
            ax.annotate("did not fit", (int(r["n"]), RAM_TOTAL_KB), xytext=(-6, -14),
                        textcoords="offset points", ha="right", color=COLORS[r["model"]])
    ax.axhline(RAM_TOTAL_KB, color="black", lw=0.8, ls="--")
    ax.text(1, RAM_TOTAL_KB + 8, f"RAM total ({RAM_TOTAL_KB} KB)")
    ax.set_xlabel("number of tasks $N$")
    ax.set_ylabel("reserved RAM (KB)")
    ax.set_xticks([1, 2, 4, 8, 16, 31])
    ax.set_ylim(0, RAM_TOTAL_KB * 1.12)
    ax.yaxis.set_major_formatter(FMT)
    ax.legend(loc="center right")
    fig.savefig(out / "a_ram.pdf")
    plt.close(fig)


def pooled(cfg_dir: Path, metric: str) -> np.ndarray:
    runs = load_config(cfg_dir)
    return np.concatenate([metrics(r)[metric] for r in runs]) / 1000 if runs else np.array([])


def fig_b_hist(raw: Path, out: Path, payload: int = 64) -> None:
    """cyclictest-style histogram: counts on a log scale, 10 us bins."""
    data = {m: pooled(raw / "B" / f"B_{m}_p{payload}", "latency") for m in B_MODELS}
    top = max(d.max() for d in data.values())
    bins = np.arange(0, top + 0.01, 0.01)
    fig, axes = plt.subplots(3, 1, figsize=(6.3, 7.2), sharex=True, sharey=True)
    for ax, m in zip(axes, B_MODELS):
        d = data[m]
        ax.hist(d, bins=bins, color=COLORS[m], histtype="stepfilled", ec=COLORS[m], lw=0.8)
        for q, ls in ((0.5, "-"), (0.99, "--"), (0.999, ":")):
            ax.axvline(np.quantile(d, q, method="inverted_cdf"), color="black", lw=0.8, ls=ls)
        ax.set_yscale("log")
        ax.set_ylim(0.7, 2e4)
        ax.set_axisbelow(True)
        ax.set_yticks([1, 10, 100, 1000, 10000], ["1", "10", "100", "1,000", "10,000"])
        ax.yaxis.set_minor_formatter(NullFormatter())
        ax.text(0.99, 0.85, LABELS[m], transform=ax.transAxes, ha="right",
                bbox=dict(fc="white", ec="none", pad=1))
    axes[1].set_ylabel("number of activations")
    axes[-1].set_xlabel(f"latency (ms), {payload}-byte payload")
    axes[-1].set_xlim(0, top * 1.03)
    axes[-1].xaxis.set_major_formatter(FMT)
    hs = [plt.Line2D([], [], color="black", lw=0.8, ls=ls) for ls in ("-", "--", ":")]
    axes[0].legend(hs, ["median", "p99", "p99.9"], loc="upper center", ncol=3,
                   bbox_to_anchor=(0.5, 1.2))
    fig.savefig(out / "b_hist.pdf")
    plt.close(fig)


C_HIST_SLICES = [1_000, 10_000, 50_000, 100_000]
C_HIST_BINS = np.geomspace(0.4, 300, 241)


def fig_c_hist(raw: Path, out: Path) -> None:
    """Histogram of the T4 response time per S, in logarithmic bins."""
    fig, axes = plt.subplots(len(C_HIST_SLICES), 1, figsize=(6.3, 7.8), sharex=True, sharey=True)
    for ax, s in zip(axes, C_HIST_SLICES):
        for m in C_MODELS:
            d = pooled(raw / "C" / f"C_{m}_s{s}", "response")
            counts, edges = np.histogram(d, bins=C_HIST_BINS)
            ax.stairs(counts, edges, fill=True, color=COLORS[m], alpha=0.45, label=LABELS[m])
            ax.stairs(counts, edges, color=COLORS[m], lw=0.8)
        ax.axvline(DEADLINE_MS, color="#c0392b", lw=1, ls="--")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_ylim(0.7, 2e4)
        ax.set_yticks([1, 10, 100, 1000, 10000], ["1", "10", "100", "1,000", "10,000"])
        ax.yaxis.set_minor_formatter(NullFormatter())
        ax.set_axisbelow(True)
        ax.text(0.01, 0.85, f"$S$ = {num(s / 1000)} ms", transform=ax.transAxes)
    axes[-1].set_xlim(0.4, 300)
    axes[-1].set_xticks([0.5, 1, 3, 10, 30, 100, 300], ["0.5", "1", "3", "10", "30", "100", "300"])
    axes[-1].xaxis.set_minor_formatter(NullFormatter())
    axes[-1].set_xlabel("response time (ms)")
    fig.supylabel("number of activations")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=3,
               bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out / "c_hist.pdf")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", type=Path, default=Path("data/results/zbook"))
    ap.add_argument("--raw", type=Path, default=Path("data/raw/zbook"))
    ap.add_argument("--out", type=Path, default=Path("data/results/zbook/figures"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    fig_a_ram(args.results, args.out)
    fig_b_hist(args.raw, args.out)
    fig_c_hist(args.raw, args.out)


if __name__ == "__main__":
    main()
