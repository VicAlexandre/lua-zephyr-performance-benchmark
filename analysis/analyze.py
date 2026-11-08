"""Statistical analysis of the experiments.

Reads the raw data from data/raw and writes CSV tables to data/results:

  B_summary.csv, C_summary.csv  summaries per configuration and metric: median,
                                quartiles, p99 and p99.9 with 95 % CIs from a
                                hierarchical bootstrap, maximum and outliers (Tukey)
  B_overhead.csv                overhead of each model over delivery in C
  B_diff.csv, C_diff.csv        differences between models, with CIs
  C_viability.csv               timing criterion: upper CI bound of the p99
                                and p99.9 response time against the deadline
  A_footprint.csv               footprint per configuration, RAM of the Lua layer
  A_fit.csv                     fit RAM = a + bN per model
  A_viability.csv               largest viable N per model and budget R

Usage:
    python analysis/analyze.py [--raw data/raw] [--out data/results]
                               [--reps 10000] [--seed 1]
"""

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

QUANTILE_METHOD = "inverted_cdf"
STATS = {"median": 0.5, "q1": 0.25, "q3": 0.75, "p99": 0.99, "p999": 0.999}
DEADLINE_US = 100_000
P_VIAB = ("p99", "p999")
BUDGETS_KB = [32, 64, 128, 256, 384]


@dataclass
class Run:
    header: dict[str, str]
    probe_c: int
    probe_lua: int | None
    heaps: list[dict[str, str]]
    samples: np.ndarray


def _kv(line: str) -> dict[str, str]:
    return dict(item.split("=", 1) for item in line.split()[1:] if "=" in item)


def parse_run(path: Path) -> Run:
    header, heaps, rows = {}, [], []
    probe_c, probe_lua = 0, None
    in_table = False
    for line in path.read_text().splitlines():
        if line.startswith("#BENCH"):
            header = _kv(line)
        elif line.startswith("#PROBE"):
            kv = _kv(line)
            if kv["where"] == "c":
                probe_c = int(kv["cycles"])
            else:
                probe_lua = int(kv["cycles"])
        elif line.startswith("#HEAP"):
            heaps.append(_kv(line))
        elif line.startswith("seq,"):
            in_table = True
        elif in_table and re.match(r"^\d+,", line):
            rows.append([int(x) for x in line.split(",")])
    warmup = int(header.get("warmup", 0))
    data = np.array([r[1:] for r in rows if r[0] >= warmup], dtype=np.uint64)
    return Run(header, probe_c, probe_lua, heaps, data.reshape(-1, 3))


def metrics(run: Run) -> dict[str, np.ndarray]:
    """Intervals in us, with the probe cost subtracted (mod 2^32 arithmetic)."""
    hz = int(run.header["hz"])
    probe = run.probe_lua if run.probe_lua is not None else run.probe_c
    t0, t1, t2 = (run.samples[:, i].astype(np.int64) for i in range(3))
    wrap = lambda d: np.mod(d, 2**32)
    to_us = lambda c: (c - probe) * 1e6 / hz
    return {
        "latency": to_us(wrap(t1 - t0)),
        "exec": to_us(wrap(t2 - t1)),
        "response": to_us(wrap(t2 - t0)),
    }


def load_config(cfg_dir: Path) -> list[Run]:
    return [parse_run(p) for p in sorted(cfg_dir.glob("run_*.txt"))]


def boot_stats(groups: list[np.ndarray], reps: int, rng: np.random.Generator,
               batch: int = 250) -> dict[str, np.ndarray]:
    groups = [g for g in groups if len(g)]
    n_runs = len(groups)
    n = min(len(g) for g in groups)
    mat = np.stack([g[:n] for g in groups])
    out = {k: np.empty(reps) for k in STATS}
    for start in range(0, reps, batch):
        b = min(batch, reps - start)
        runs = rng.integers(0, n_runs, size=(b, n_runs))
        idx = rng.integers(0, n, size=(b, n_runs, n))
        res = mat[runs[:, :, None], idx].reshape(b, -1)
        for k, p in STATS.items():
            out[k][start:start + b] = np.quantile(res, p, axis=1, method=QUANTILE_METHOD)
    return out


def ci(values: np.ndarray) -> tuple[float, float]:
    lo, hi = np.percentile(values, [2.5, 97.5])
    return float(lo), float(hi)


def summarize(groups: list[np.ndarray], boot: dict[str, np.ndarray]) -> dict[str, float]:
    pooled = np.concatenate(groups)
    row: dict[str, float] = {"runs": len(groups), "n": len(pooled)}
    for k, p in STATS.items():
        row[k] = float(np.quantile(pooled, p, method=QUANTILE_METHOD))
        row[f"{k}_lo"], row[f"{k}_hi"] = ci(boot[k])
    row["max"] = float(pooled.max())
    iqr = row["q3"] - row["q1"]
    row["tukey_out"] = int(np.sum((pooled < row["q1"] - 1.5 * iqr) |
                                  (pooled > row["q3"] + 1.5 * iqr)))
    return row


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.3f}" if isinstance(v, float) else v) for k, v in r.items()})


def analyze_temporal(exp: str, raw: Path, reps: int, rng: np.random.Generator):
    """Summaries and bootstrap per configuration and metric (Experiments B and C)."""
    summary, boots = [], {}
    for cfg_dir in sorted((raw / exp).glob(f"{exp}_*")):
        runs = load_config(cfg_dir)
        if not runs:
            continue
        per_metric: dict[str, list[np.ndarray]] = {}
        for run in runs:
            for m, v in metrics(run).items():
                per_metric.setdefault(m, []).append(v)
        for m, groups in per_metric.items():
            boot = boot_stats(groups, reps, rng)
            boots[(cfg_dir.name, m)] = boot
            fails = sum(int(h["alloc_fail"]) for r in runs for h in r.heaps)
            summary.append({"config": cfg_dir.name, "metric": m, **summarize(groups, boot),
                            "alloc_fail": fails})
    return summary, boots


def diff_row(name: str, metric: str, a: dict, b: dict) -> dict:
    row = {"comparison": name, "metric": metric}
    for k in ("median", "p99", "p999"):
        d = a[k] - b[k]
        lo, hi = ci(d)
        row[f"d_{k}"] = float(np.median(d))
        row[f"d_{k}_lo"], row[f"d_{k}_hi"] = lo, hi
        row[f"d_{k}_signif"] = int(lo > 0 or hi < 0)
    return row


def analyze_b(raw: Path, out: Path, reps: int, rng: np.random.Generator) -> None:
    summary, boots = analyze_temporal("B", raw, reps, rng)
    write_csv(out / "B_summary.csv", summary)
    overhead, diffs = [], []
    payloads = sorted({int(c.split("_p")[1]) for c, _ in boots})
    for p in payloads:
        base = boots.get((f"B_BASE_p{p}", "latency"))
        for model in ("MT", "MC"):
            m = boots.get((f"B_{model}_p{p}", "latency"))
            if base is not None and m is not None:
                overhead.append({"payload": p, **diff_row(f"{model}-BASE", "latency", m, base)})
        for metric in ("latency", "exec", "response"):
            mt, mc = boots.get((f"B_MT_p{p}", metric)), boots.get((f"B_MC_p{p}", metric))
            if mt is not None and mc is not None:
                diffs.append({"payload": p, **diff_row("MT-MC", metric, mt, mc)})
    write_csv(out / "B_overhead.csv", overhead)
    write_csv(out / "B_diff.csv", diffs)


def analyze_c(raw: Path, out: Path, reps: int, rng: np.random.Generator) -> None:
    summary, boots = analyze_temporal("C", raw, reps, rng)
    write_csv(out / "C_summary.csv", summary)
    viab = []
    for r in summary:
        if r["metric"] != "response":
            continue
        row = {"config": r["config"], "deadline_us": DEADLINE_US}
        for k in P_VIAB:
            row[f"{k}_us"], row[f"{k}_hi_us"] = r[k], r[f"{k}_hi"]
            row[f"viable_{k}"] = int(r[f"{k}_hi"] <= DEADLINE_US)
        viab.append(row)
    write_csv(out / "C_viability.csv", viab)
    diffs = []
    slices = sorted({int(c.split("_s")[1]) for c, _ in boots})
    for s in slices:
        mc = boots.get((f"C_MC_s{s}", "response"))
        for other in ("MTEQ", "MTSPLIT"):
            mt = boots.get((f"C_{other}_s{s}", "response"))
            if mc is not None and mt is not None:
                diffs.append({"slice_us": s, **diff_row(f"{other}-MC", "response", mt, mc)})
    write_csv(out / "C_diff.csv", diffs)


def _read_kv(path: Path) -> dict[str, str]:
    return dict(l.split("=", 1) for l in path.read_text().split() if "=" in l) \
        if path.exists() else {}


def analyze_a(raw: Path, out: Path) -> None:
    ref = _read_kv(raw / "A" / "A_NONE" / "footprint.txt")
    if not ref:
        return
    ref_ram, ref_flash = int(ref["ram_used"]), int(ref["flash_bin"])
    rows = []
    for cfg_dir in sorted((raw / "A").glob("A_M*_n*")):
        model, level = re.match(r"A_(\w+)_n(\w+)", cfg_dir.name).groups()
        fp = _read_kv(cfg_dir / "footprint.txt")
        row = {"model": model, "n": level, "fits": int(fp.get("fits", 0))}
        if row["fits"]:
            runs = load_config(cfg_dir)
            peaks: dict[str, int] = {}
            for r in runs:
                for h in r.heaps:
                    peaks[h["name"]] = max(peaks.get(h["name"], 0), int(h["peak"]))
            row.update({
                "flash_bin": int(fp["flash_bin"]),
                "flash_lua": int(fp["flash_bin"]) - ref_flash,
                "ram_reserved": int(fp["ram_used"]),
                "ram_lua": int(fp["ram_used"]) - ref_ram,
                "heap_peak_sum": sum(peaks.values()),
                "alloc_fail": sum(int(h["alloc_fail"]) for r in runs for h in r.heaps),
                "runs": len(runs),
            })
        rows.append(row)
    write_csv(out / "A_footprint.csv", rows)

    fits, viab = [], []
    for model in ("MT", "MC"):
        pts = [(int(r["n"]), r["ram_lua"]) for r in rows
               if r["model"] == model and r["fits"] and r["n"].isdigit()]
        if len(pts) >= 2:
            n, ram = np.array(pts, dtype=float).T
            b, a = np.polyfit(n, ram, 1)
            fits.append({"model": model, "a_bytes": float(a), "b_bytes_per_task": float(b),
                         "points": len(pts)})
        for kb in BUDGETS_KB:
            ok = [n for n, ram in pts if ram <= kb * 1024]
            viab.append({"model": model, "budget_kb": kb, "max_n": max(ok) if ok else 0})
    write_csv(out / "A_fit.csv", fits)
    write_csv(out / "A_viability.csv", viab)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--out", type=Path, default=Path("data/results"))
    ap.add_argument("--reps", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    analyze_a(args.raw, args.out)
    analyze_b(args.raw, args.out, args.reps, rng)
    analyze_c(args.raw, args.out, args.reps, rng)

if __name__ == "__main__":
    main()
