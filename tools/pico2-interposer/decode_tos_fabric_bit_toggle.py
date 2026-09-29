#!/usr/bin/env python3
"""Decode the guarded, reversible first-TOS fabric bit-11 readout."""

import argparse
import hashlib
from pathlib import Path
import re


START = 0x03c3fffc
GUARD_PASSED = 0x03c3fff8
GUARD_FAILED = 0x03c3ffe0
RESTORE_FAILED = 0x03c3ffec
SAFE_END = 0x03c3fff0


def value(low, high):
    if (not 0x03c40000 <= low < 0x03c80000 or
            not 0x03c80000 <= high < 0x03cc0000 or
            (low | high) & 3):
        raise ValueError('invalid encoded read addresses')
    return (((high - 0x03c80000) >> 2) << 16 |
            ((low - 0x03c40000) >> 2))


def decode(raw):
    lines = raw.splitlines()
    if len(lines) < 3 or lines[-1] != 'DIAG-END':
        raise ValueError('incomplete Pico diagnostic dump')
    header = re.fullmatch(r'DIAG count=(\d+) stored=(\d+)', lines[0])
    if not header:
        raise ValueError('wrong Pico diagnostic header')
    count, stored = map(int, header.groups())
    words = [int(token, 16) for line in lines[1:-1] for token in line.split()]
    if count < stored or len(words) != stored or not words or words[0] != START:
        raise ValueError('missing or truncated start marker')
    if len(words) > 1 and words[1] == GUARD_FAILED:
        return {'status': 'guard-failed'}
    if len(words) < 9 or words[1] != GUARD_PASSED:
        raise ValueError('missing guard-passed marker')
    measured = [value(*words[index:index + 2]) for index in (2, 4, 6)]
    if words[8] == RESTORE_FAILED:
        return {'status': 'restore-failed', 'fabric_set': measured[0],
                'harvest_set': measured[1], 'fabric_restore': measured[2]}
    if len(words) < 11 or words[10] != SAFE_END:
        raise ValueError('missing safe end marker')
    harvest_restored = value(*words[8:10])
    return {'status': 'safe', 'fabric_set': measured[0],
            'harvest_set': measured[1], 'fabric_restore': measured[2],
            'harvest_restore': harvest_restored}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    args = parser.parse_args()
    data = args.trace.read_bytes()
    result = decode(data.decode())
    print('SHA256', hashlib.sha256(data).hexdigest())
    for key, entry in result.items():
        print(f'{key}={entry:#010x}' if isinstance(entry, int) else f'{key}={entry}')


if __name__ == '__main__':
    main()
