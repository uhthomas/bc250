#!/usr/bin/env python3
"""Restore the RAM-only original-BIOS CS# relay after Pico USB recovery."""

import argparse
from pathlib import Path
import subprocess
import time

import serial


def exchange(port, command):
    port.reset_input_buffer()
    port.write(command.encode() + b'\n')
    port.flush()
    return port.readline().decode(errors='replace').strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uf2', type=Path, required=True)
    parser.add_argument('--picotool', type=Path,
                        default=Path('/home/pi/.local/bin/picotool'))
    parser.add_argument('--serial', type=Path, default=Path('/dev/ttyACM0'))
    args = parser.parse_args()
    if not args.uf2.is_file():
        parser.error('UF2 not found')
    subprocess.run([str(args.picotool), 'reboot', '-f', '-u'], check=True,
                   stdout=subprocess.DEVNULL)
    time.sleep(0.8)
    subprocess.run([str(args.picotool), 'load', '-v', '-x', str(args.uf2),
                    '--vid', '0x2e8a', '--pid', '0x000f'], check=True,
                   stdout=subprocess.DEVNULL)
    deadline = time.monotonic() + 9
    last = 'Pico USB serial not available'
    while time.monotonic() < deadline:
        try:
            with serial.Serial(str(args.serial), 115200, timeout=0.5) as port:
                before = exchange(port, 'status')
                if not before.startswith('BC250-PICO2-CS-PASS v2 '):
                    last = before
                    time.sleep(0.1)
                    continue
                if not all(token in before for token in
                           ('armed=0', 'gate=0', 'miso=INPUT',
                            'bios_write=UNAVAILABLE')):
                    raise RuntimeError(f'unsafe pre-arm state: {before}')
                reply = exchange(port, 'arm-pass')
                after = exchange(port, 'status')
                if (not reply.startswith('ARMED CS-PASS GP7=open-drain-sink')
                        or not all(token in after for token in
                                   ('armed=1', 'gate=1', 'miso=INPUT',
                                    'bios_write=UNAVAILABLE'))):
                    raise RuntimeError(f'arm failed: {reply}; {after}')
                print(before)
                print(reply)
                print(after)
                return
        except (FileNotFoundError, serial.SerialException) as error:
            last = str(error)
            time.sleep(0.1)
    raise RuntimeError(f'Pico did not arm before deadline: {last}')


if __name__ == '__main__':
    main()
