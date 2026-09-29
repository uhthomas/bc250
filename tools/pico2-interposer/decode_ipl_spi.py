#!/usr/bin/env python3
"""Reconstruct a private IPL slice from the Pico's RAM-only SPI read trace."""
import argparse
import hashlib
import os
from pathlib import Path
import re


def decode(text, halfwords, marked=False):
    lines = text.splitlines()
    if len(lines) < 3 or lines[-1] != 'DIAG-END':
        raise ValueError('incomplete Pico diagnostic dump')
    match = re.fullmatch(r'DIAG count=(\d+) stored=(\d+)', lines[0])
    if not match:
        raise ValueError('wrong Pico diagnostic header')
    count, stored = (int(group) for group in match.groups())
    if count < stored:
        raise ValueError('invalid Pico diagnostic count')
    words = [int(token, 16) for line in lines[1:-1] for token in line.split()]
    if len(words) != stored:
        raise ValueError(f'expected {stored} stored addresses, got {len(words)}')
    if marked:
        start = [0x03c3fffc, 0x03c3fff8, 0x03c3fff4]
        end = [0x03c3fff0, 0x03c3ffec, 0x03c3ffe8]
        windows = []
        for index in range(len(words) - len(start) + 1):
            if words[index:index + len(start)] != start:
                continue
            for stop in range(index + len(start), len(words) - len(end) + 1):
                if words[stop:stop + len(end)] != end:
                    continue
                window = words[index + len(start):stop]
                # The stock BIOS occasionally reads these 64-byte runs while
                # the PSP hook is running. They are not encoded halfwords.
                for base in (0x03c31c00, 0x03c31c40, 0x03c20000):
                    burst = [base + 4 * offset for offset in range(16)]
                    positions = [i for i in range(len(window) - 15)
                                 if window[i:i + 16] == burst]
                    if len(positions) > 1:
                        raise ValueError(f'ambiguous BIOS burst {base:08x}')
                    if positions:
                        where = positions[0]
                        window = window[:where] + window[where + 16:]
                if len(window) == halfwords:
                    windows.append(window)
                break
        if len(windows) != 1:
            raise ValueError(f'expected one complete {halfwords}-halfword marked slice, got {len(windows)}')
        words = windows[0]
    elif len(words) != halfwords:
        raise ValueError(f'expected {halfwords} addresses, got {len(words)}')
    result = bytearray()
    for index, command in enumerate(words):
        if not 0x03c00000 <= command < 0x03c40000 or command & 3:
            raise ValueError(f'bad diagnostic command #{index}: {command:08x}')
        result += ((command - 0x03c00000) >> 2).to_bytes(2, 'little')
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--halfwords', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--marked', action='store_true')
    args = parser.parse_args()
    data = decode(args.trace.read_text(), args.halfwords, args.marked)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
    print(f'{args.output}: {len(data)} bytes SHA256 {hashlib.sha256(data).hexdigest()}')


if __name__ == '__main__':
    main()
