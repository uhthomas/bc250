#!/usr/bin/env python3
"""Load a guarded no-flash Pico UF2 and arm it before its pre-arm watchdog.

Run on the Pi while the BC250 is powered off. The script rejects the wrong
profile and refuses to proceed unless the Pico reports a fault-free arm.
"""
import argparse
from pathlib import Path
import subprocess
import time

import serial


def read_line(port, command):
    port.reset_input_buffer()
    port.write(command.encode() + b'\n')
    port.flush()
    return port.readline().decode(errors='replace').strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--uf2', required=True, type=Path)
    ap.add_argument('--profile', required=True)
    ap.add_argument('--picotool', type=Path, default=Path('/home/pi/.local/bin/picotool'))
    ap.add_argument('--serial', type=Path, default=Path('/dev/ttyACM0'))
    a = ap.parse_args()
    if not a.uf2.is_file():
        ap.error('UF2 not found')
    start = time.monotonic()
    subprocess.run([str(a.picotool), 'reboot', '-f', '-u'], check=True,
                   stdout=subprocess.DEVNULL)
    time.sleep(0.8)
    subprocess.run([str(a.picotool), 'load', '-v', '-x', str(a.uf2),
                    '--vid', '0x2e8a', '--pid', '0x000f'], check=True,
                   stdout=subprocess.DEVNULL)
    deadline = time.monotonic()+8
    last = 'Pico USB serial not available'
    while time.monotonic() < deadline:
        try:
            with serial.Serial(str(a.serial), 115200, timeout=0.4) as port:
                status = read_line(port, 'status')
                if f'profile={a.profile} ' not in status:
                    last = f'wrong or incomplete profile: {status}'
                    time.sleep(0.1)
                    continue
                if 'mode=0' not in status or 'fault=0' not in status or 'host_cs=1' not in status:
                    raise RuntimeError(f'unsafe pre-arm state: {status}')
                armed = read_line(port, 'arm-active')
                after = read_line(port, 'status')
                if ('ARMED SPARSE-ACTIVE' not in armed or
                        f'profile={a.profile} ' not in after or
                        'mode=2' not in after or 'fault=0' not in after):
                    raise RuntimeError(f'arm not verified: {armed!r}; {after!r}')
                print(f'Elapsed {time.monotonic()-start:.1f}s')
                print(status)
                print(armed)
                print(after)
                return
        except (FileNotFoundError, serial.SerialException) as error:
            last = str(error)
            time.sleep(0.1)
    raise RuntimeError(f'Pico did not arm before deadline: {last}')


if __name__ == '__main__':
    main()
