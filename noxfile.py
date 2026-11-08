"""Tasks to build, flash and run the experiments.

General usage:
    nox -s build -- samples/dwt_check            # build for the Zbook
    nox -s build -- app -DBENCH_EXP=B -DBENCH_MODEL=MC
    nox -s flash -- samples/dwt_check            # flash the latest build
    nox -s monitor [-- /dev/ttyACM1]             # serial console
    nox -s clean                                 # remove build/

Experiments, with options after `--`:
    nox -s calibrate                  # bytes per table slot -> app/calibration.conf
    nox -s exp_a                      # footprint
    nox -s exp_b                      # dispatch latency
    nox -s exp_c                      # cooperative blocking
    nox -s run_all -- --detach        # A, B and C in sequence, unattended (tmux)
    nox -s status                     # collection progress and remaining time
    nox -s analyze                    # statistics in data/results/zbook
    options: --runs 10  --port /dev/ttyACM0  --only <regex>  --fresh (redo everything)  --allow-dirty

"""

import argparse
import os
import shlex
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import nox

nox.options.default_venv_backend = "none"
nox.options.sessions = ["build"]

ROOT = Path(__file__).parent
APP = ROOT / "app"
DATA_ROOT = ROOT / "data" / "raw"
BOARD = "zbook/rp2350b/m33"
DEFAULT_APP = "app"

A_LEVELS = ["1", "2", "4", "8", "16", "31", "FULL"]
B_PAYLOADS = [1, 16, 64, 256, 1024]
C_SLICES_US = [100, 300, 1_000, 3_000, 10_000, 30_000, 50_000, 100_000]

HEAP_MARGIN = 1.40
PROBE_HEAP_MAX = 131_072
PROBE_BUDGET_MT = 393_216


def _app_and_extra(session: nox.Session) -> tuple[Path, list[str]]:
    """Split the application path from the extra CMake arguments."""
    args = list(session.posargs)
    app = (
        Path(args.pop(0)) if args and not args[0].startswith("-") else Path(DEFAULT_APP)
    )
    if not (ROOT / app / "CMakeLists.txt").exists():
        session.error(f"application not found: {app}")
    return app, args


def _build_dir(app: Path) -> Path:
    return ROOT / "build" / app.name


@nox.session
def build(session: nox.Session) -> None:
    """Build an application for the Zbook."""
    app, extra = _app_and_extra(session)
    cmd = [
        "west",
        "build",
        "-p",
        "auto",
        "-b",
        BOARD,
        "-d",
        str(_build_dir(app)),
        str(ROOT / app),
    ]
    if extra:
        cmd += ["--", *extra]
    session.run(*cmd, external=True)


@nox.session
def flash(session: nox.Session) -> None:
    """Flash the latest build of the application through the RP2040 (OpenOCD/CMSIS-DAP)."""
    app, _ = _app_and_extra(session)
    build_dir = _build_dir(app)
    if not build_dir.exists():
        session.error(f"{build_dir} does not exist; run first: nox -s build -- {app}")
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from capture import west_flash_cmd

    session.run(*west_flash_cmd(build_dir), external=True)


@nox.session
def monitor(session: nox.Session) -> None:
    """Open the Zbook serial console (default /dev/ttyACM0, 115200 baud; Ctrl+] exits)."""
    port = session.posargs[0] if session.posargs else "/dev/ttyACM0"
    session.run(
        "python", "-m", "serial.tools.miniterm", "--raw", port, "115200", external=True
    )


@nox.session
def clean(session: nox.Session) -> None:
    """Remove all build directories."""
    shutil.rmtree(ROOT / "build", ignore_errors=True)


@dataclass
class Config:
    name: str
    args: dict[str, str] = field(default_factory=dict)

    def cmake_args(self) -> list[str]:
        return [f"-D{k}={v}" for k, v in self.args.items()]


def _options(session: nox.Session) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog=f"nox -s {session.name} --")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument(
        "--only", default="", help="only the configurations whose name matches this regex"
    )
    ap.add_argument("--timeout", type=float, default=3600)
    ap.add_argument(
        "--fresh",
        action="store_true",
        help="redo everything, ignoring runs and heap sizings already recorded",
    )
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help="allow collecting on the Zbook with uncommitted changes",
    )
    ap.add_argument(
        "--exps", default="A,B,C", help="run_all: experiments, in order (default A,B,C)"
    )
    ap.add_argument(
        "--detach",
        action="store_true",
        help="run_all: run in the background, in a tmux session 'benchmark'",
    )
    return ap.parse_args(session.posargs)


def _data(opts: argparse.Namespace) -> Path:
    return DATA_ROOT / "zbook"


def _cfg_build_dir(opts: argparse.Namespace, cfg: Config) -> Path:
    return ROOT / "build" / cfg.name


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True
    ).stdout.strip()


def _provenance(session: nox.Session, opts: argparse.Namespace, exp: str) -> None:
    """Record the firmware commit and the frozen manifest alongside the data.
    Refuse to collect with uncommitted changes."""
    dirty = _git("status", "--porcelain")
    if dirty and not opts.allow_dirty:
        session.error(
            "lua-zephyr-performance-benchmark has uncommitted changes; commit them before "
            "collecting (or use --allow-dirty)"
        )
    frozen = subprocess.run(
        ["west", "manifest", "--freeze"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    out = _data(opts) / exp / "PROVENANCE.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if dirty or not _git("rev-parse", "--verify", "HEAD"):
        files = _git("ls-files", "--cached", "--others", "--exclude-standard").split(
            "\n"
        )
        files = [f for f in files if f and not f.startswith("data/")]
        snap = out.parent / f"source-{stamp}.tar.gz"
        subprocess.run(["tar", "czf", str(snap), "-C", str(ROOT), *files], check=True)
    with out.open("a") as f:
        f.write(
            f"# session {session.name} at {datetime.now().isoformat(timespec='seconds')}\n"
            f"lua-zephyr-performance-benchmark {_git('rev-parse', '--verify', 'HEAD') or 'no commit'}"
            f"{' (with uncommitted changes; code in source-' + stamp + '.tar.gz)' if dirty else ''}\n"
            f"options {vars(opts)}\n{frozen}\n"
        )


def _build_cfg(
    session: nox.Session, opts: argparse.Namespace, cfg: Config, check: bool = True
) -> str | None:
    """Build the configuration; return the log, or None if it fails without check."""
    cmd = [
        "west",
        "build",
        "-p",
        "always",
        "-b",
        BOARD,
        "-d",
        str(_cfg_build_dir(opts, cfg)),
        str(APP),
        "--",
        *cfg.cmake_args(),
    ]
    session.log(f"building {cfg.name}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        if check:
            session.error(
                f"failed to build {cfg.name}:\n{proc.stdout[-3000:]}{proc.stderr[-3000:]}"
            )
        return None
    return proc.stdout


def _validate(text: str) -> list[str]:
    """Problems that invalidate a run; empty list if it is valid."""
    problems = []
    if "Lua error" in text:
        problems.append("Lua error during the run")
    m = re.search(r"#GEN pub_errors=(\d+)", text)
    if m is None:
        problems.append("no #GEN line")
    elif int(m.group(1)) > 0:
        problems.append(f"{m.group(1)} publications failed")
    fails = sum(int(x) for x in re.findall(r"#HEAP .*alloc_fail=(\d+)", text))
    if fails:
        problems.append(f"{fails} allocation failures")
    rows = re.findall(r"^\d+,(\d+),(\d+),(\d+)", text, re.M)
    empty = sum(1 for t0, t1, t2 in rows if "0" in (t0, t1, t2))
    if empty:
        problems.append(f"{empty} samples missing one of the t0, t1 or t2 timestamps")
    return problems


def _done(opts: argparse.Namespace, out: Path) -> bool:
    """Run already recorded and valid (resume), unless --fresh."""
    return not opts.fresh and out.exists() and not _validate(out.read_text())


def _capture(
    session: nox.Session,
    opts: argparse.Namespace,
    cfg: Config,
    out: Path,
    strict: bool = True,
) -> tuple[Path, list[str]]:
    """Run and validate. With strict, an invalid run aborts the session;
    without strict, the problems are returned for the caller to decide."""
    session.log(f"running {cfg.name} -> {out.relative_to(ROOT)}")
    session.run(
        "python",
        str(ROOT / "scripts" / "capture.py"),
        str(_cfg_build_dir(opts, cfg)),
        str(out),
        "--port",
        opts.port,
        "--timeout",
        str(opts.timeout),
        external=True,
    )
    problems = _validate(out.read_text())
    if problems:
        bad = out.with_suffix(".invalid.txt")
        out.replace(bad)
        if strict:
            session.error(
                f"{cfg.name}: invalid run ({'; '.join(problems)}); "
                f"output kept in {bad.relative_to(ROOT)}"
            )
        return bad, problems
    return out, []


def _run_path(opts: argparse.Namespace, exp: str, cfg: Config, run: int) -> Path:
    return _data(opts) / exp / cfg.name / f"run_{run:02d}.txt"


def _run_interleaved(
    session: nox.Session, opts: argparse.Namespace, exp: str, groups: list[list[Config]]
) -> None:
    """Run each group (one factor level, one item per model), interleaving
    the models on every repetition. Runs already recorded and valid are skipped."""
    _provenance(session, opts, exp)
    for group in groups:
        group = [c for c in group if re.search(opts.only, c.name)]
        pending = [
            c
            for c in group
            if not all(
                _done(opts, _run_path(opts, exp, c, r)) for r in range(1, opts.runs + 1)
            )
        ]
        if not pending:
            continue
        sized = []
        for cfg in group:
            res = _size_heaps(session, opts, cfg, _data(opts) / exp)
            if res is None:
                session.error(f"{cfg.name}: did not fit in RAM")
            sized.append(res[0])
        for run in range(1, opts.runs + 1):
            for cfg in sized:
                out = _run_path(opts, exp, cfg, run)
                if not _done(opts, out):
                    _capture(session, opts, cfg, out)


def _heap_lines(path: Path) -> list[dict[str, str]]:
    heaps = []
    for line in path.read_text().splitlines():
        if line.startswith("#HEAP"):
            heaps.append(dict(kv.split("=", 1) for kv in line.split()[1:]))
    return heaps


def _footprint(build_log: str, build_dir: Path) -> dict[str, int]:
    fp = {"flash_bin": (build_dir / "zephyr" / "zephyr.bin").stat().st_size}
    for region, used, unit in re.findall(
        r"^\s*(FLASH|RAM):\s+(\d+)\s+(B|KB)", build_log, re.M
    ):
        fp[f"{region.lower()}_used"] = int(used) * (1024 if unit == "KB" else 1)
    return fp


def _lua_threads(cfg: Config) -> int:
    """Number of Lua threads (states) in the configuration."""
    model, exp = cfg.args.get("BENCH_MODEL"), cfg.args.get("BENCH_EXP")
    if model == "MC":
        return 1
    if model != "MT":
        return 0
    if exp == "A":
        n = cfg.args.get("BENCH_N", "1")
        return 6 if n == "FULL" else int(n)
    return 2 if exp == "C" else 1


def _probe_heap(cfg: Config) -> int:
    return min(PROBE_HEAP_MAX, PROBE_BUDGET_MT // _lua_threads(cfg) // 256 * 256)


def _size_heaps(
    session: nox.Session, opts: argparse.Namespace, cfg: Config, exp_dir: Path
) -> tuple[Config, str] | None:
    """Probe the peak of each Lua heap with headroom and return the configuration
    with heaps of peak + 40 %, already built, and the build log. Reuse a sizing
    already recorded (heaps.txt). Return None if the configuration does not fit
    in RAM, including when the probe heap, limited by the available RAM, is not
    enough for the tasks (Experiment A)."""
    if _lua_threads(cfg) == 0:
        log = _build_cfg(session, opts, cfg, check=False)
        return (cfg, log) if log is not None else None

    heaps_file = exp_dir / cfg.name / "heaps.txt"
    if heaps_file.exists() and not opts.fresh:
        sized = {
            **cfg.args,
            **dict(l.split("=", 1) for l in heaps_file.read_text().split()),
        }
    else:
        probe = Config(cfg.name, {**cfg.args, "BENCH_HEAP": str(_probe_heap(cfg))})
        if _build_cfg(session, opts, probe, check=False) is None:
            return None
        out, problems = _capture(
            session, opts, probe, exp_dir / cfg.name / "probe.txt", strict=False
        )
        if problems:
            if cfg.args.get("BENCH_EXP") == "A":
                session.log(
                    f"{cfg.name}: probe heap too small "
                    f"({'; '.join(problems)}); did not fit in RAM"
                )
                return None
            session.error(f"{cfg.name}: invalid probe ({'; '.join(problems)})")
        sized = dict(cfg.args)
        for h in _heap_lines(out):
            size = int(int(h["peak"]) * HEAP_MARGIN + 7) // 8 * 8
            key = (
                "BENCH_HEAP"
                if cfg.args["BENCH_MODEL"] == "MC"
                else f"BENCH_HEAP_{h['name']}"
            )
            sized[key] = str(size)

    final = Config(cfg.name, sized)
    log = _build_cfg(session, opts, final, check=False)
    if log is None:
        return None
    heaps_file.write_text(
        "".join(f"{k}={v}\n" for k, v in sized.items() if k.startswith("BENCH_HEAP"))
    )
    return final, log


def _configs_a() -> list[Config]:
    cfgs = [Config("A_NONE", {"BENCH_EXP": "A", "BENCH_MODEL": "NONE"})]
    for level in A_LEVELS:
        for model in ("MT", "MC"):
            cfgs.append(
                Config(
                    f"A_{model}_n{level}",
                    {"BENCH_EXP": "A", "BENCH_MODEL": model, "BENCH_N": level},
                )
            )
    return cfgs


def _groups_b() -> list[list[Config]]:
    return [
        [
            Config(
                f"B_{m}_p{p}",
                {"BENCH_EXP": "B", "BENCH_MODEL": m, "BENCH_PAYLOAD": str(p)},
            )
            for m in ("MT", "MC", "BASE")
        ]
        for p in B_PAYLOADS
    ]


def _groups_c() -> list[list[Config]]:
    return [
        [
            Config(
                f"C_MC_s{s}",
                {"BENCH_EXP": "C", "BENCH_MODEL": "MC", "BENCH_SLICE_US": str(s)},
            ),
            Config(
                f"C_MTEQ_s{s}",
                {
                    "BENCH_EXP": "C",
                    "BENCH_MODEL": "MT",
                    "BENCH_SLICE_US": str(s),
                    "BENCH_PRIO": "EQUAL",
                },
            ),
            Config(
                f"C_MTSPLIT_s{s}",
                {
                    "BENCH_EXP": "C",
                    "BENCH_MODEL": "MT",
                    "BENCH_SLICE_US": str(s),
                    "BENCH_PRIO": "SPLIT",
                },
            ),
        ]
        for s in C_SLICES_US
    ]


@nox.session
def calibrate(session: nox.Session) -> None:
    """Measure the table slot size and the probe cost; write app/calibration.conf."""
    opts = _options(session)
    cfg = Config("CAL", {"BENCH_EXP": "CAL"})
    _build_cfg(session, opts, cfg)
    out, _ = _capture(session, opts, cfg, _data(opts) / "CAL" / "cal.txt")

    text = out.read_text()
    slots, nbytes = re.search(r"#CAL table slots=(\d+) bytes=([\d.]+)", text).groups()
    slot_bytes = max(1, round(float(nbytes) / int(slots)))

    session.log(f"SLOT_BYTES={slot_bytes}")
    (APP / "calibration.conf").write_text(f"CONFIG_BENCH_SLOT_BYTES={slot_bytes}\n")


def _exp_a(session: nox.Session, opts: argparse.Namespace) -> None:
    exp_dir = _data(opts) / "A"
    _provenance(session, opts, "A")

    for cfg in _configs_a():
        if not re.search(opts.only, cfg.name):
            continue
        cfg_dir = exp_dir / cfg.name
        cfg_dir.mkdir(parents=True, exist_ok=True)
        if cfg.args["BENCH_MODEL"] == "NONE":
            log = _build_cfg(session, opts, cfg)
            (cfg_dir / "footprint.txt").write_text(
                "".join(
                    f"{k}={v}\n"
                    for k, v in _footprint(log, _cfg_build_dir(opts, cfg)).items()
                )
            )
            continue
        runs = [cfg_dir / f"run_{r:02d}.txt" for r in range(1, opts.runs + 1)]
        if (cfg_dir / "footprint.txt").exists() and all(_done(opts, r) for r in runs):
            continue
        res = _size_heaps(session, opts, cfg, exp_dir)
        if res is None:
            session.log(f"{cfg.name}: did not fit in RAM")
            (cfg_dir / "footprint.txt").write_text("fits=0\n")
            continue
        sized, log = res
        (cfg_dir / "footprint.txt").write_text(
            "fits=1\n"
            + "".join(
                f"{k}={v}\n"
                for k, v in _footprint(log, _cfg_build_dir(opts, sized)).items()
            )
        )
        for out in runs:
            if not _done(opts, out):
                _capture(session, opts, sized, out)


@nox.session
def exp_a(session: nox.Session) -> None:
    """Experiment A: Flash and RAM footprint as a function of N."""
    _exp_a(session, _options(session))


@nox.session
def exp_b(session: nox.Session) -> None:
    """Experiment B: dispatch latency per payload (MT, MC and baseline)."""
    _run_interleaved(session, _options(session), "B", _groups_b())


@nox.session
def exp_c(session: nox.Session) -> None:
    """Experiment C: T4 response time under the T2 background task."""
    _run_interleaved(session, _options(session), "C", _groups_c())


@nox.session
def run_all(session: nox.Session) -> None:
    """Run the experiments (A, B and C in sequence), unattended.

    Prevents the computer from sleeping (systemd-inhibit) and writes all output to
    data/raw/zbook/run_all.log. With --detach, runs in a tmux session 'benchmark'
    (follow with `tmux attach -t benchmark`; detach with Ctrl+b d). If interrupted,
    just repeat the command: runs already recorded and valid are skipped.
    """
    opts = _options(session)
    exps = [e.strip().upper() for e in opts.exps.split(",") if e.strip()]
    if any(e not in ("A", "B", "C") for e in exps):
        session.error(f"--exps accepts A, B and C; got {opts.exps}")
    args = [a for a in session.posargs if a != "--detach"]
    log = _data(opts) / "run_all.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    if opts.detach:
        if shutil.which("tmux") is None:
            session.error("tmux not found")
        if (
            subprocess.run(
                ["tmux", "has-session", "-t", "benchmark"], capture_output=True
            ).returncode
            == 0
        ):
            session.error(
                "a tmux session 'benchmark' already exists (tmux attach -t benchmark)"
            )
        cmd = f"cd {shlex.quote(str(ROOT))} && direnv exec . nox -s run_all -- {shlex.join(args)}"
        subprocess.run(["tmux", "new-session", "-d", "-s", "benchmark", cmd], check=True)
        session.log(
            f"run_all started in tmux session 'benchmark'; log in {log.relative_to(ROOT)}"
        )
        session.log(
            "follow: tmux attach -t benchmark   |   detach without stopping: Ctrl+b d"
        )
        return

    if os.environ.get("BENCH_RUN_ALL") is None:
        inner = f"set -o pipefail; nox -s run_all -- {shlex.join(args)} 2>&1 | tee -a {shlex.quote(str(log))}"
        cmd = ["bash", "-c", inner]
        if shutil.which("systemd-inhibit"):
            cmd = [
                "systemd-inhibit",
                "--what=sleep:idle",
                "--who=lua-zephyr-performance-benchmark",
                "--why=benchmark run",
                *cmd,
            ]
        else:
            session.warn("systemd-inhibit not found: the computer may go to sleep")
        session.run(*cmd, external=True, env={"BENCH_RUN_ALL": "1"})
        return

    session.log(f"run_all: {', '.join(exps)} ({datetime.now():%Y-%m-%d %H:%M})")
    for exp in exps:
        session.log(f"=== Experiment {exp} ===")
        if exp == "A":
            _exp_a(session, opts)
        elif exp == "B":
            _run_interleaved(session, opts, "B", _groups_b())
        else:
            _run_interleaved(session, opts, "C", _groups_c())
    session.log(f"run_all finished ({datetime.now():%Y-%m-%d %H:%M})")


@nox.session
def analyze(session: nox.Session) -> None:
    """Statistical analysis and figures: data/raw/zbook -> data/results/zbook."""
    raw, out = DATA_ROOT / "zbook", ROOT / "data" / "results" / "zbook"
    session.run(
        "python",
        str(ROOT / "analysis" / "analyze.py"),
        "--raw",
        str(raw),
        "--out",
        str(out),
        *session.posargs,
        external=True,
    )
    session.run(
        "python",
        str(ROOT / "analysis" / "plots.py"),
        "--results",
        str(out),
        "--raw",
        str(raw),
        "--out",
        str(out / "figures"),
        external=True,
    )


def _run_seconds(cfg: Config) -> float:
    """Estimated duration of a run (collection, flashing, boot and output)."""
    n = 1100
    exp = cfg.args.get("BENCH_EXP")
    if exp == "A":
        return 10 + 1 + 6
    if exp == "B":
        return n * 0.015 + 1 + 8
    s = int(cfg.args["BENCH_SLICE_US"]) / 1e6
    m = max(2.5 * s, 0.020)
    return n * 1.5 * m + max(1.0, 3 * s) + 8


@nox.session
def status(session: nox.Session) -> None:
    """Collection progress: ready, invalid and pending runs, with a time estimate.

    Only reads the files in data/raw; can be called at any time, including
    while run_all is running. Accepts --runs.
    """
    opts = _options(session)
    data = _data(opts)
    exps = {
        "A": [c for c in _configs_a() if c.args["BENCH_MODEL"] != "NONE"],
        "B": [c for g in _groups_b() for c in g],
        "C": [c for g in _groups_c() for c in g],
    }
    total_left = 0.0
    lines = [
        f"{'exp':<4}{'ready':>9}{'invalid':>11}{'pending':>11}"
        f"{'no fit':>11}{'remaining':>11}"
    ]
    newest = None
    for exp, cfgs in exps.items():
        done = bad = pend = nofit = 0
        left = 0.0
        for cfg in cfgs:
            d = data / exp / cfg.name
            if (d / "footprint.txt").exists() and "fits=0" in (
                d / "footprint.txt"
            ).read_text():
                nofit += 1
                continue
            bad += len(list(d.glob("*.invalid.txt"))) if d.exists() else 0
            probe_left = _lua_threads(cfg) > 0 and not (d / "heaps.txt").exists()
            missing = 0
            for r in range(1, opts.runs + 1):
                out = d / f"run_{r:02d}.txt"
                if out.exists() and not _validate(out.read_text()):
                    done += 1
                    mt = out.stat().st_mtime
                    newest = mt if newest is None or mt > newest else newest
                else:
                    missing += 1
            pend += missing
            left += (missing + probe_left) * _run_seconds(cfg)
        total_left += left
        lines.append(
            f"{exp:<4}{done:>9}{bad:>11}{pend:>11}{nofit:>11}{left / 3600:>9.1f} h"
        )
    for line in lines:
        session.log(line)
    session.log(f"estimated remaining time: {total_left / 3600:.1f} h")
    if newest is not None:
        session.log(
            f"latest recorded run: {datetime.fromtimestamp(newest):%Y-%m-%d %H:%M:%S}"
        )
    alive = (
        shutil.which("tmux")
        and subprocess.run(
            ["tmux", "has-session", "-t", "benchmark"], capture_output=True
        ).returncode
        == 0
    )
    session.log(f"tmux session 'benchmark': {'active' if alive else 'not running'}")
