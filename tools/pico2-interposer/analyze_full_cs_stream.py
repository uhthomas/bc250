#!/usr/bin/env python3
"""Validate the lossless RLE SPI command trace through the last changed word."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from analyze_cs_pass_hunt import analyze as analyze_filtered
from cs_pass_hunt import RANGES


def expand(binary, metadata):
    if (not metadata.get('usable_for_ordering') or metadata.get('overflow') or
            metadata.get('stall') or metadata.get('cancelled') or
            hashlib.sha256(binary).hexdigest() != metadata['binary_sha256'] or
            len(binary) != metadata['records'] * 8):
        raise ValueError('invalid or incomplete RLE capture')
    commands = []
    for start, count in struct.iter_unpack('<II', binary):
        if count == 0:
            raise ValueError('zero-length RLE record')
        commands.extend((start + 4 * i) & 0xffffffff for i in range(count))
    if len(commands) != metadata['seen'] or len(commands) != metadata['sent']:
        raise ValueError('RLE expansion count mismatch')
    return commands


def filtered_hits(commands):
    return [dict(transaction=i, command=f'{word:08x}',
                 previous=f'{commands[i-1]:08x}' if i else '00000000',
                 previous2=f'{commands[i-2]:08x}' if i > 1 else '00000000')
            for i, word in enumerate(commands)
            if word >> 24 == 3 and any(lo <= (word & 0xffffff) < hi for lo, hi in RANGES)]


def run_count(commands):
    return bool(commands) + sum(b != ((a + 4) & 0xffffffff)
                                for a, b in zip(commands, commands[1:]))


def analyze(binary, metadata, old_filtered, clean, patched):
    commands = expand(binary, metadata)
    hits = filtered_hits(commands)
    old_hits = old_filtered['hits']
    if len(hits) != len(old_hits) or len(hits) != 3727:
        raise ValueError('new and prior filtered hit counts differ')
    if [(x['command'], x['previous'], x['previous2']) for x in hits[:3712]] != [
        (x['command'], x['previous'], x['previous2']) for x in old_hits[:3712]]:
        raise ValueError('new and prior filtered boot sequences differ')
    pseudo = dict(usable_for_ordering=True, overflow=0, stall=0, hits=hits)
    filtered_audit = analyze_filtered(pseudo, clean, patched)
    first, second = (p['keydb_read_starts'][0] for p in filtered_audit['passes'])
    comparable = min(second - first, len(commands) - second)
    common = 0
    while common < comparable and commands[first + common] == commands[second + common]:
        common += 1
    changed = {a for a in range(0, len(clean), 4)
               if clean[a:a+4] != patched[a:a+4]}
    last_changed = []
    for lo, hi in ((first, second), (second, len(commands))):
        occurrences = [i for i in range(lo, hi) if
                       commands[i] >> 24 == 3 and (commands[i] & 0xffffff) in changed]
        if not occurrences:
            raise ValueError('no changed-word read in a boot pass')
        last_changed.append(occurrences[-1])
    required_prefix = max(last_changed[0] - first, last_changed[1] - second) + 1
    if common < required_prefix:
        raise ValueError('full command streams diverged before last changed word')
    scope = commands[first:first + required_prefix]
    if any(word >> 24 != 3 or word & 3 for word in scope):
        raise ValueError('non-READ03 or unaligned command within required scope')
    return dict(schema=1, full_stream_sha256=metadata['binary_sha256'],
                observed_commands=len(commands), rle_records=metadata['records'],
                prior_filtered_boot_hits_match=True,
                first_keydb_transaction=first, second_keydb_transaction=second,
                second_pass_offset=second-first,
                exact_common_commands=common,
                first_full_mismatch_relative=common if common < comparable else None,
                last_changed_relative=required_prefix-1,
                identical_through_last_changed=True,
                required_scope_commands=required_prefix,
                required_scope_rle_runs=run_count(scope),
                changed_words=filtered_audit['changed_words'],
                filtered_hits_per_pass=filtered_audit['passes'][0]['filtered_hits'],
                first_type50_read_is_copy_in_native_model=True,
                active_route_timing_unmeasured=True,
                firmware_injection_tested=False,
                board_patch_profile_ready=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', required=True, type=Path)
    p.add_argument('--metadata', required=True, type=Path)
    p.add_argument('--filtered', required=True, type=Path)
    p.add_argument('--clean', required=True, type=Path)
    p.add_argument('--patched', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = analyze(args.binary.read_bytes(), json.loads(args.metadata.read_text()),
                     json.loads(args.filtered.read_text()), args.clean.read_bytes(),
                     args.patched.read_bytes())
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
