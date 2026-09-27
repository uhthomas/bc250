#!/usr/bin/env python3
"""Validate repeated BC250 filtered boot commands against the retained overlay.

Only the selected address ranges and two predecessor words were captured;
matching those records does not prove the intervening SPI traffic matched.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


ANCHOR = ('039db040', '039db03c', '039db038')


def analyze(capture, clean, patched):
    if not capture.get('usable_for_ordering') or capture.get('overflow') or capture.get('stall'):
        raise ValueError('capture has a dropped/invalid command indication')
    if len(clean) != len(patched) or len(clean) != 0x1000000:
        raise ValueError('expected equal 16 MiB ROMs')
    hits = capture['hits']
    anchors = [i for i, hit in enumerate(hits) if
               tuple(hit[key] for key in ('command', 'previous', 'previous2')) == ANCHOR]
    if len(anchors) != 4:
        raise ValueError(f'expected two KEYDB reads per pass in two passes, got {len(anchors)}')
    first, second = anchors[0], anchors[2]
    length = second - first
    a, b = hits[first:second], hits[second:second + length]
    if len(b) != length or not all(
        (x['command'], x['previous'], x['previous2']) ==
        (y['command'], y['previous'], y['previous2']) for x, y in zip(a, b)
    ):
        raise ValueError('filtered passes differ')
    offsets = {y['transaction'] - x['transaction'] for x, y in zip(a, b)}
    if len(offsets) != 1:
        raise ValueError('pass transaction offsets differ')
    changed = {address for address in range(0, len(clean), 4)
               if clean[address:address + 4] != patched[address:address + 4]}
    regions = {'type50': (0x9dad00, 0x9dbad0),
               'tos': (0x8eac00, 0x8fef50),
               'driver': (0x984f00, 0x99f670)}
    if any(sum(lo <= address < hi for lo, hi in regions.values()) != 1
           for address in changed):
        raise ValueError('changed word outside expected overlay regions')
    passes = []
    for group in (a, b):
        addresses = Counter(int(hit['command'], 16) & 0xffffff for hit in group)
        missing = sorted(changed - addresses.keys())
        if missing:
            raise ValueError(f'changed words absent from a pass: {missing[:8]}')
        by_region = {}
        for name, (lo, hi) in regions.items():
            relevant = [address for address in changed if lo <= address < hi]
            by_region[name] = dict(changed_words=len(relevant),
                                   observed_instances=sum(addresses[address] for address in relevant),
                                   min_instances=min(addresses[address] for address in relevant),
                                   max_instances=max(addresses[address] for address in relevant))
        keydb_starts = [hit['transaction'] for hit in group if
                        tuple(hit[key] for key in ('command', 'previous', 'previous2')) == ANCHOR]
        if len(keydb_starts) != 2:
            raise ValueError('KEYDB two-read pattern missing within pass')
        passes.append(dict(first_transaction=group[0]['transaction'],
                           last_transaction=group[-1]['transaction'],
                           filtered_hits=len(group), keydb_read_starts=keydb_starts,
                           changed_words_seen=len(changed), regions=by_region))
    return dict(schema=1, capture_image=capture.get('image'),
                clean_sha256=hashlib.sha256(clean).hexdigest(),
                patched_sha256=hashlib.sha256(patched).hexdigest(),
                filtered_passes_equal=True,
                constant_transaction_offset=next(iter(offsets)),
                changed_words=len(changed), passes=passes,
                extra_filtered_hits=len(hits) - (second + length),
                full_bus_captured=False, board_patch_profile_ready=False,
                firmware_injection_tested=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', required=True, type=Path)
    parser.add_argument('--clean', required=True, type=Path)
    parser.add_argument('--patched', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = analyze(json.loads(args.capture.read_text()),
                     args.clean.read_bytes(), args.patched.read_bytes())
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
