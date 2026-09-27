#!/usr/bin/env python3
"""Run a Pi-only SPI0-to-PIO loopback after the three jumper pairs are wired.

This drives GPIO8/10/11 through SPI0. Never run it with any BC250 connection.
The explicit --pi-only-wired flag is required before opening SPI0.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import tempfile
import time

from analyze import analyze

HERE = Path(__file__).resolve().parent
CAPTURE = HERE / "bc250-spi-capture"
SENDER = HERE / "bc250-loopback-spi"
WORDS = 2300


def expected_words():
    words = []
    for _ in range(2):
        for start, end in ((0x9DAE00, 0x9DB8D0), (0x9DBC00, 0x9DC040)):
            words.extend((0x03 << 24) | addr for addr in range(start, end, 4))
    words.extend((0x03 << 24) | addr for addr in range(0x10000, 0x14000, 4))
    return words[:WORDS]


def stop_capture(process):
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi-only-wired", action="store_true",
                        help="confirm only Pi pins 24→11, 23→13, 19→15 are joined")
    parser.add_argument("--hz", type=int, default=1_000_000)
    parser.add_argument("--mode3", action="store_true")
    parser.add_argument("--out-parent", type=Path, default=Path("/tmp"))
    args = parser.parse_args()
    if not args.pi_only_wired:
        parser.error("no SPI0 output without --pi-only-wired and the BC250/CH347 disconnected")
    if not 100_000 <= args.hz <= 50_000_000:
        parser.error("--hz must be between 100000 and 50000000")
    for path in (CAPTURE, SENDER, Path("/dev/pio0"), Path("/dev/spidev0.0")):
        if not path.exists():
            parser.error(f"required Pi device or binary missing: {path}")
    for pin in (17, 22, 27):
        state = subprocess.run(["pinctrl", "get", str(pin)], text=True,
                               capture_output=True, check=True).stdout
        if not state.lstrip().startswith(f"{pin}: no "):
            parser.error(f"GPIO{pin} is not unused before capture: {state.strip()}")

    os.umask(0o077)
    out = Path(tempfile.mkdtemp(prefix="bc250-pi-loopback-", dir=args.out_parent))
    raw = out / "capture.raw"
    log = out / "capture.log"
    process = None
    try:
        command = [str(CAPTURE), "--output", str(raw), "--words", str(WORDS)]
        if args.mode3:
            command.append("--mode3")
        with log.open("w") as stream:
            process = subprocess.Popen(command, cwd=HERE, stdout=subprocess.DEVNULL,
                                       stderr=stream)
            deadline = time.monotonic() + 10
            while "READY:" not in log.read_text():
                if process.poll() is not None:
                    raise RuntimeError(f"capture exited before READY; see {log}")
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"capture did not reach READY; see {log}")
                time.sleep(0.05)

            sender_command = [str(SENDER), "--hz", str(args.hz)]
            if args.mode3:
                sender_command.append("--mode3")
            sender = subprocess.run(sender_command, cwd=HERE, text=True,
                                    capture_output=True, timeout=30, check=False)
            (out / "sender.log").write_text(sender.stdout + sender.stderr)
            if sender.returncode:
                raise RuntimeError(f"SPI0 sender failed ({sender.returncode}); see {out/'sender.log'}")
            try:
                capture_status = process.wait(timeout=20)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError(f"capture did not fill after SPI0 sender; see {log}") from exc
            if capture_status:
                raise RuntimeError(f"capture failed ({capture_status}); see {log}")
    finally:
        stop_capture(process)

    data = raw.read_bytes()
    if len(data) != 4 * WORDS:
        raise RuntimeError(f"capture has {len(data)} bytes, expected {4 * WORDS}; see {out}")
    observed = struct.unpack(f"<{WORDS}I", data)
    expected = expected_words()
    mismatch = next((index for index, (a, b) in enumerate(zip(observed, expected))
                     if a != b), None)
    report = analyze(data)
    result = {
        "scope": "Pi-only wired SPI0-to-PIO command capture; no BC250 attached",
        "requested_hz": args.hz,
        "mode": 3 if args.mode3 else 0,
        "command_words": WORDS,
        "exact_expected_sequence": mismatch is None,
        "first_mismatch_command_word": mismatch,
        "expected_at_first_mismatch": hex(expected[mismatch]) if mismatch is not None else None,
        "observed_at_first_mismatch": hex(observed[mismatch]) if mismatch is not None else None,
        "analysis": report,
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print("loopback files", out)
    print("requested SPI0 Hz", args.hz, "exact 2300-command match", mismatch is None)
    if mismatch is not None:
        raise RuntimeError(f"SPI command mismatch at word {mismatch}; inspect {out/'result.json'}")


if __name__ == "__main__":
    main()
