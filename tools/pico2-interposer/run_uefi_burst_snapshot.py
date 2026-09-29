#!/usr/bin/env python3
"""Load RAM-only CS relay capture while BC250 is idle, then collect later.

Run `arm` on the Pi before cold-cycling the BC250; run `collect` after boot.
MISO is input-only. This script never writes either device's SPI flash.
"""

import argparse
import os
from pathlib import Path
import subprocess
import time

import serial


def exchange(port, command):
    port.reset_input_buffer()
    port.write(command.encode() + b'\n')
    port.flush()
    return port.readline().decode(errors='replace').strip()


def arm(args):
    if not args.uf2 or not args.uf2.is_file():
        raise ValueError('arm requires an existing --uf2')
    subprocess.run([str(args.picotool), 'reboot', '-f', '-u'], check=True)
    time.sleep(0.8)
    subprocess.run([str(args.picotool), 'load', '-v', '-x', str(args.uf2),
                    '--vid', '0x2e8a', '--pid', '0x000f'], check=True)
    deadline = time.monotonic() + 9
    last = 'serial unavailable'
    while time.monotonic() < deadline:
        try:
            with serial.Serial(str(args.serial), 115200, timeout=0.5) as port:
                status = exchange(port, 'status')
                if 'BC250-PICO2-CS-PASS-BURST v1' not in status:
                    last = status
                    time.sleep(0.1)
                    continue
                if ('armed=0' not in status or 'miso_oe=0' not in status or
                        (not args.recovery_allow_low and 'host_cs=1' not in status)):
                    raise RuntimeError(f'unsafe pre-arm state: {status}')
                reply = exchange(port, 'arm-pass-recovery' if args.recovery_allow_low else 'arm-pass')
                after = exchange(port, 'status')
                if ('ARMED CS-PASS-BURST MISO=INPUT' not in reply or
                        'armed=1' not in after or 'miso_oe=0' not in after):
                    raise RuntimeError(f'arm failed: {reply}; {after}')
                print(status)
                print(reply)
                print(after)
                return
        except (FileNotFoundError, serial.SerialException) as error:
            last = str(error)
            time.sleep(0.1)
    raise RuntimeError(f'Pico did not arm before watchdog: {last}')


def collect(args):
    if not args.output:
        raise ValueError('collect requires --output')
    with serial.Serial(str(args.serial), 115200, timeout=2) as port:
        status = exchange(port, 'status')
        print(status)
        if ('BC250-PICO2-CS-PASS-BURST v1' not in status or
                'armed=1' not in status or 'capture_started=1' not in status or
                'remaining=0' not in status or 'watch_rxstall=0' not in status):
            raise RuntimeError('capture absent, incomplete or command watcher stalled')
        port.reset_input_buffer()
        port.write(b'dump\n')
        port.flush()
        lines = []
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and len(lines) <= 1030:
            line = port.readline().decode('ascii', errors='strict')
            if not line:
                continue
            lines.append(line)
            if line.strip() == 'BURST-END':
                break
    if not lines or not lines[0].startswith('BURST-SNAPSHOT words=1024') or lines[-1].strip() != 'BURST-END':
        raise RuntimeError('bad or incomplete burst dump')
    payload = ''.join(lines).encode()
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(payload)
    print(f'wrote {len(payload)} bytes to {args.output}')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['arm', 'collect'])
    ap.add_argument('--uf2', type=Path)
    ap.add_argument('--output', type=Path)
    ap.add_argument('--picotool', type=Path, default=Path('/home/pi/.local/bin/picotool'))
    ap.add_argument('--serial', type=Path, default=Path('/dev/ttyACM0'))
    ap.add_argument('--recovery-allow-low', action='store_true',
                    help='arm input-only CS relay while host CS is low; PIO waits for high before relaying')
    args = ap.parse_args()
    {'arm': arm, 'collect': collect}[args.action](args)


if __name__ == '__main__':
    main()
