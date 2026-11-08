"""Run a build and capture the experiment output.

Each run starts from a reset: the script opens the Zbook serial port, flashes
the image with `west flash` (which resets the board) and reads the console
up to the `#END` line.

Usage:
    python scripts/capture.py BUILD_DIR OUTPUT.txt [--port /dev/ttyACM0] [--timeout 1800]
"""

import argparse
import os
import subprocess
import sys
import threading
from pathlib import Path

END = "#END"


def west_flash_cmd(build_dir: Path) -> list[str]:
    """`west flash`, using the OpenOCD from OPENOCD/OPENOCD_SCRIPTS when set."""
    cmd = ["west", "flash", "-d", str(build_dir)]
    if os.environ.get("OPENOCD"):
        cmd += ["--openocd", os.environ["OPENOCD"]]
    if os.environ.get("OPENOCD_SCRIPTS"):
        cmd += ["--openocd-search", os.environ["OPENOCD_SCRIPTS"]]
    return cmd


def capture_zbook(build_dir: Path, port: str, baud: int, timeout: float) -> list[str]:
    import serial

    lines: list[str] = []
    done = threading.Event()
    failure: list[BaseException] = []

    with serial.Serial(port, baud, timeout=0.5) as ser:
        ser.reset_input_buffer()

        def reader() -> None:
            buf = b""
            while not done.is_set():
                try:
                    buf += ser.read(4096)
                except serial.SerialException as e:
                    failure.append(e)
                    done.set()
                    return
                *complete, buf = buf.split(b"\n")
                for raw in complete:
                    line = raw.decode(errors="replace").rstrip("\r")
                    lines.append(line)
                    if line.startswith(END):
                        done.set()

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        flash = subprocess.run(west_flash_cmd(build_dir), capture_output=True, text=True)
        if flash.returncode != 0:
            done.set()
            sys.stderr.write(flash.stdout + flash.stderr)
            raise RuntimeError("flashing failed")
        if not done.wait(timeout):
            done.set()
            raise TimeoutError(f"no {END} after {timeout} s")
        t.join()
        if failure:
            raise RuntimeError(f"serial port lost: {failure[0]}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("build_dir", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--timeout", type=float, default=1800)
    args = ap.parse_args()

    lines = capture_zbook(args.build_dir, args.port, args.baud, args.timeout)

    if not any(line.startswith(END) for line in lines):
        sys.stderr.write("\n".join(lines[-20:]) + "\n")
        raise RuntimeError(f"run ended without {END}")

    start = max((i for i, l in enumerate(lines) if "#BOOT" in l), default=0)
    lines[start] = lines[start][lines[start].find("#BOOT"):]
    end = next(i for i, l in enumerate(lines) if l.startswith(END))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines[start:end + 1]) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
