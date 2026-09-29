#!/usr/bin/env python3
"""Decode the fixed first-TOS VCN policy read-address sequence."""

import argparse
import hashlib
from pathlib import Path
import re


MARKERS = (0x03c3fffc, 0x03c3fff8, 0x03c3fff4, 0x03c3fff0)
TARGETS = (0x1f820, 0x1f8a4, 0x1f81c)


def decode(raw, targets=TARGETS):
    lines = raw.splitlines()
    if len(lines) < 3 or lines[-1] != 'DIAG-END':
        raise ValueError('incomplete Pico diagnostic dump')
    match = re.fullmatch(r'DIAG count=(\d+) stored=(\d+)', lines[0])
    if not match or int(match.group(2)) < 10:
        raise ValueError('missing diagnostic addresses')
    words = [int(token, 16) for line in lines[1:-1] for token in line.split()]
    if len(words) != int(match.group(2)):
        raise ValueError('truncated Pico diagnostic dump')
    values = []
    for i, target in enumerate(targets):
        marker, low, high = words[i * 3:i * 3 + 3]
        if marker != MARKERS[i]:
            raise ValueError(f'{target:#x}: wrong marker {marker:#x}')
        if (not 0x03c40000 <= low < 0x03c80000 or
            not 0x03c80000 <= high < 0x03cc0000 or
            (low | high) & 3):
            raise ValueError(f'{target:#x}: invalid encoded read addresses')
        values.append(((high - 0x03c80000) >> 2) << 16 |
                      ((low - 0x03c40000) >> 2))
    if words[9] != MARKERS[3]:
        raise ValueError('missing end marker')
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--targets', nargs=3, type=lambda value: int(value, 0),
                        default=TARGETS)
    args = parser.parse_args()
    data = args.trace.read_bytes()
    values = decode(data.decode(), args.targets)
    print('SHA256', hashlib.sha256(data).hexdigest())
    for target, value in zip(args.targets, values):
        print(f'{target:#07x} = {value:#010x}')


if __name__ == '__main__':
    main()
