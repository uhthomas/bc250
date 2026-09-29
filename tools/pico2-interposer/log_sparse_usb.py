#!/usr/bin/env python3
"""Persist sparse Pico status and four SPI diagnostic addresses on the Pi."""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import termios
import time

import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', type=Path, default=Path('/dev/ttyACM0'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=90)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 180:
        parser.error('seconds must be 1..180')
    if args.output.exists():
        parser.error('output already exists')
    end = time.monotonic() + args.seconds
    with args.output.open('x', buffering=1) as log:
        while time.monotonic() < end:
            candidates = sorted(Path('/dev').glob('ttyACM*'))
            if args.serial.exists() and args.serial not in candidates:
                candidates.insert(0, args.serial)
            if len(candidates) != 1:
                print(datetime.now(timezone.utc).isoformat(),
                      'SERIAL_DEVICE_COUNT', len(candidates), file=log, flush=True)
                time.sleep(0.8)
                continue
            try:
                with serial.Serial(str(candidates[0]), 115200, timeout=0.4) as port:
                    print(datetime.now(timezone.utc).isoformat(),
                          'SERIAL_OPEN', str(candidates[0]), file=log, flush=True)
                    os.fsync(log.fileno())
                    while time.monotonic() < end:
                        port.reset_input_buffer()
                        port.write(b'status\n')
                        status = port.readline().decode(errors='replace').strip()
                        port.write(b'diag-dump\n')
                        diag = port.read_until(b'DIAG-END\n', size=300).decode(
                            errors='replace').strip().replace('\n', ' | ')
                        print(datetime.now(timezone.utc).isoformat(),
                              status, diag, file=log, flush=True)
                        os.fsync(log.fileno())
                        time.sleep(0.8)
            except (OSError, serial.SerialException, termios.error) as error:
                print(datetime.now(timezone.utc).isoformat(),
                      'SERIAL_ERROR', repr(error), file=log, flush=True)
                os.fsync(log.fileno())
                time.sleep(0.8)


if __name__ == '__main__':
    main()
