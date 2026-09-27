#!/usr/bin/env python3
"""Collect filtered BC250 command/predecessor context through Pico CS pass-through."""
import argparse
import json
from pathlib import Path
import time

from capture import Serial, private_write

MAX_HITS = 16384
RANGES = ((0x8eabd0, 0x8eb080), (0x8f0800, 0x8f0c00),
          (0x8fed50, 0x8ff050), (0x99f470, 0x99f770),
          (0x9db040, 0x9db340))


def parse(header, lines, footer):
    if not header.startswith('HITS '):
        raise ValueError('missing HITS header')
    try:
        fields = dict(item.split('=', 1) for item in header[5:].split())
        seen, kept, overflow, stall, cancelled = (
            int(fields[k]) for k in ('seen', 'kept', 'overflow', 'stall', 'cancelled'))
    except (ValueError, KeyError) as exc:
        raise ValueError('invalid HITS header') from exc
    if (footer != 'DONEH' or len(lines) != kept or kept > MAX_HITS or
            seen < kept + overflow or min(seen, kept, overflow, stall, cancelled) < 0):
        raise ValueError('truncated or inconsistent capture')
    hits = []
    previous_index = -1
    for line in lines:
        try:
            index_str, command_str, previous_str, previous2_str = line.split()
            index = int(index_str)
            command = int(command_str, 16)
            previous = int(previous_str, 16)
            previous2 = int(previous2_str, 16)
        except ValueError as exc:
            raise ValueError('invalid hit line: ' + line) from exc
        address = command & 0xffffff
        if (index <= previous_index or index >= seen or command >> 24 != 3 or
                not any(first <= address < last for first, last in RANGES) or
                any(word > 0xffffffff for word in (command, previous, previous2))):
            raise ValueError('out-of-order or invalid hit: ' + line)
        hits.append(dict(transaction=index, command=f'{command:08x}',
                         previous=f'{previous:08x}', previous2=f'{previous2:08x}'))
        previous_index = index
    return dict(seen=seen, kept=kept, overflow=overflow, stall=stall,
                cancelled=bool(cancelled), hits=hits,
                usable_for_ordering=not (overflow or stall or cancelled))


def collect(port, output, timeout):
    if not 1 <= timeout <= 120:
        raise ValueError('timeout must be 1..120 seconds')
    if output.exists():
        raise FileExistsError(output)
    serial = Serial(port)
    pending = False
    try:
        serial.write(b'\nstatus\n')
        deadline = time.monotonic() + 5
        banner = ''
        for _ in range(10):
            banner = serial.line(deadline)
            if banner.startswith('BC250-PICO2-CS-PASS-HUNT v1 '):
                break
        if (not banner.startswith('BC250-PICO2-CS-PASS-HUNT v1 ') or
                'armed=1 gate=1' not in banner or
                'bios_write=UNAVAILABLE' not in banner):
            raise ValueError('requires armed CS-PASS-HUNT image: ' + banner)
        serial.write(f'hunt-pass {timeout * 1000}\n'.encode())
        pending = True
        armed = serial.line(time.monotonic() + 5)
        if not armed.startswith('ARMED HUNT-PASS ') or 'outputs=CS_ONLY' not in armed:
            raise ValueError(armed)
        print(armed + ' — reboot the BC250 now', flush=True)
        header = serial.line(time.monotonic() + timeout + 15)
        if not header.startswith('HITS '):
            raise ValueError(header)
        try:
            kept = int(dict(item.split('=', 1) for item in header[5:].split())['kept'])
        except (KeyError, ValueError) as exc:
            raise ValueError('invalid hit count') from exc
        if not 0 <= kept <= MAX_HITS:
            raise ValueError('invalid kept hit count')
        transfer_deadline = time.monotonic() + 90
        lines = [serial.line(transfer_deadline) for _ in range(kept)]
        footer = serial.line(transfer_deadline)
        pending = False
        result = parse(header, lines, footer)
        result.update(schema=1, image='CS-PASS-HUNT-v1', clock_hz=200000000,
                      board_flash_written=False, pico_flash_written=False,
                      ranges=[dict(first=f'{a:06x}', last_exclusive=f'{b:06x}')
                              for a, b in RANGES])
        private_write(output, (json.dumps(result, indent=2) + '\n').encode())
        print(json.dumps({k: v for k, v in result.items() if k != 'hits'}, indent=2))
    finally:
        if pending:
            try:
                serial.write(b'x\n', timeout=1)
            except (OSError, TimeoutError):
                pass
        serial.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--timeout', type=int, default=35)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    collect(args.port, args.output, args.timeout)


if __name__ == '__main__':
    main()
