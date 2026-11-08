# lua-zephyr-performance-benchmark

Benchmarks the two concurrency models of `lua_zephyr` on the Zbook
(RP2350B, Cortex-M33):

- **MT** (preemptive): each task gets its own Zephyr thread, Lua state and heap.
- **MC** (cooperative): tasks are coroutines that an async scheduler runs in a
  single thread.

Three experiments measure RAM and Flash footprint (A), dispatch latency (B)
and response time while a background task holds the CPU (C).

This repository is the manifest of a west T2 workspace. It holds the
applications; west clones Zephyr and the modules next to it.

```
lua-zephyr-ws/
├── lua-zephyr-performance-benchmark/   # this repository (manifest and applications)
├── zephyr/             # v4.5.0
└── modules/
    ├── lang/lua_zephyr # feat/async-coroutine-scheduler
    ├── boards/zbook    # board definition
    └── hal/            # cmsis_6, rpi_pico
```

`west.yml` pins every project to a commit.

## Requirements

- [uv](https://docs.astral.sh/uv/) and [direnv](https://direnv.net/) (with the
  shell hook set up)
- Zephyr SDK 1.0.0, expected at `~/zephyr-sdk-1.0.0`. Put a different path in
  `.envrc.local`: `export ZEPHYR_SDK_INSTALL_DIR=/path/to/sdk`
- OpenOCD with RP2350 support, to flash through the Zbook's RP2040 probe. The
  Zephyr SDK build lacks `target/rp2350.cfg`, so `.envrc` uses
  `/usr/local/bin/openocd`. Override `OPENOCD` and `OPENOCD_SCRIPTS` in
  `.envrc.local` if yours lives elsewhere.

## Workspace setup

```sh
mkdir lua-zephyr-ws && cd lua-zephyr-ws
git clone https://github.com/VicAlexandre/lua-zephyr-performance-benchmark.git
cd lua-zephyr-performance-benchmark
direnv allow          # creates .venv with uv (west, nox, Zephyr dependencies)
west init -l .
west update --narrow -o=--depth=1
```

Inside the repository, direnv gives you Python 3.12 from `uv.lock`, `west`,
`nox` and the Zephyr SDK variables.

## Building and flashing

Every task is a nox session (`noxfile.py`):

```sh
nox -s build -- samples/dwt_check              # build for zbook/rp2350b/m33
nox -s build -- app -DBENCH_EXP=B -DBENCH_MODEL=MC  # extra arguments for CMake
nox -s flash -- samples/dwt_check              # flash the latest build
nox -s monitor                                 # serial console (/dev/ttyACM0)
nox -s clean                                   # remove build/
nox -l                                         # list the sessions
```

Builds go to `build/<application-name>/`.

## Applications

| Path | Description |
|---|---|
| `app` | Benchmark firmware (calibration and experiments A, B and C) |
| `samples/xip_check` | Cost of a zbus publication and XIP cache misses (RP2350 CTR_HIT/CTR_ACC counters) |
| `samples/dwt_check` | DWT CYCCNT frequency and read cost; also checks the serial console |

## Experiments

CMake variables select each configuration of `app/`: `BENCH_EXP`,
`BENCH_MODEL`, `BENCH_N`, `BENCH_PAYLOAD`, `BENCH_SLICE_US`, `BENCH_PRIO` and
`BENCH_HEAP` (see `app/CMakeLists.txt`). `app/cmake/bench.cmake` generates the
Lua threads for each model:

- **MT**: one entry script per task, each in a thread with its own state,
  heap and `message subscriber`;
- **MC**: one script that spawns one async task per archetype in a single
  thread;
- **BASE**: C receiver for T4, without Lua (Experiment B);
- **NONE**: no tasks, reference for the fixed part of the footprint.

Both models run the same task bodies from `app/lua/tasks.lua`. Every
configuration shares the stimulus generator (`app/src/stimulus.c`), the DWT
cycle probe (`app/src/probe.c`) and the `bench` Lua library
(`app/src/lua_bench.c`).

To reproduce everything on a Zbook:

```sh
nox -s calibrate     # writes app/calibration.conf (bytes per table slot)
nox -s exp_a         # footprint: heap probing, heap = peak + 40 %, 10 runs
nox -s exp_b         # dispatch latency: MT, MC and baseline, payloads 1 to 1024 B
nox -s exp_c         # cooperative blocking: MC, MT with equal priorities and prioritized MT
nox -s analyze       # tables and figures in data/results/zbook
```

`nox -s run_all -- --detach` runs A, B and C unattended (about 11 h) in a
tmux session and keeps the computer awake; `nox -s status` shows progress. If a
session stops, run the same command again: it skips runs already recorded and
valid.

Common options after `--`: `--runs N`, `--only <regex>` (filters
configurations by name), `--port /dev/ttyACMx`, `--fresh` and `--allow-dirty`.

Two diagnostics exist for investigation: `-DBENCH_DIAG=GC` marks the end of
each garbage collector cycle with a sentinel object, and `-DBENCH_DIAG=COLS`
adds timestamps in the generator and the work loop. Leave both off when you
measure.

### Output format

Each run writes one file:

- `#BENCH`: parameters;
- `#PROBE`: probe cost;
- `#GEN`: generator counters;
- `#HEAP`: size, peak and allocation failures, one line per Lua state;
- in experiments B and C, a `seq,t0,t1,t2` table in cycles;
- `#END`.

## Collected data

`data/raw/zbook/` holds the raw data from our Zbook, one directory per
experiment and configuration. Each experiment directory has a `PROVENANCE.txt`
with the frozen manifest and a `source-*.tar.gz` with the exact code that
collected it. `nox -s analyze` turns it into the tables and figures in
`data/results/zbook/`.
