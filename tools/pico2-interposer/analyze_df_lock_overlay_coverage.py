#!/usr/bin/env python3
"""Audit what a reversible DF-lock SPI overlay must cover on recorded boots.

The RLE trace records command addresses, not transfer lengths. Only the
48-command four-byte scan and the measured 64-byte UEFI stream are assigned
lengths here; the variable prelude is reported without guessing its lengths.
This is a coverage audit, not an interposer plan or permission to flash a ROM.
"""

import argparse
import hashlib
import json
from pathlib import Path

from analyze_full_cs_stream import expand


WORKING_SHA256 = 'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183'
CANDIDATE_SHA256 = 'f3bf69891739c5143748bc975dc7030e1144fdfebf27c325dccad5d748aa7c64'
SAME_LENGTH_SHA256 = 'ae9145cfa521107ebb7e553c39877a89f822ea1960e16f83a38485b9b5fe2331'
SHORT_START = 0xAE0000
SHORT_COUNT = 48
LONG_START = 0xAE0140
LONG_MIN_COUNT = 1000


def pinned_rom(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != 16 * 1024 * 1024 or digest != expected:
        raise ValueError(f'{path}: wrong ROM size or SHA256: {digest}')
    return data


def find_scans(commands: list[int]) -> list[int]:
    pattern = [0x03000000 | (SHORT_START + 4 * i) for i in range(SHORT_COUNT)]
    return [i for i, command in enumerate(commands)
            if command == pattern[0] and commands[i:i + SHORT_COUNT] == pattern]


def find_long_runs(commands: list[int]) -> list[tuple[int, int]]:
    starts = [i for i, command in enumerate(commands)
              if command == (0x03000000 | LONG_START)]
    runs = []
    for start in starts:
        end = start + 1
        while end < len(commands) and commands[end] == commands[end - 1] + 64:
            end += 1
        if end - start >= LONG_MIN_COUNT:
            runs.append((start, end))
    return runs


def coverage(commands: list[int], working: bytes, candidate: bytes) -> dict:
    scans = find_scans(commands)
    runs = find_long_runs(commands)
    if len(scans) != 2 or len(runs) != 2:
        raise ValueError(f'expected two short scans and two long runs; got {len(scans)}, {len(runs)}')
    changed_short = [offset for offset in range(SHORT_START, SHORT_START + 4 * SHORT_COUNT, 4)
                     if working[offset:offset + 4] != candidate[offset:offset + 4]]
    passes = []
    for scan, (start, end) in zip(scans, runs):
        if not scan + SHORT_COUNT < start:
            raise ValueError('scan does not precede long run')
        # The final ae0000 before the regular stream starts its variable
        # 64-byte prelude; this does not assign a length to each command.
        prelude_starts = [i for i in range(scan + SHORT_COUNT, start)
                          if commands[i] == 0x03AE0000]
        if not prelude_starts or start - prelude_starts[-1] > 32:
            raise ValueError('missing nearby UEFI prelude')
        prelude = [command & 0xFFFFFF for command in commands[prelude_starts[-1]:start]]
        burst_offsets = [command & 0xFFFFFF for command in commands[start:end]]
        if burst_offsets[0] != LONG_START or burst_offsets != list(
                range(LONG_START, LONG_START + 64 * len(burst_offsets), 64)):
            raise ValueError('long run is not the expected aligned sequence')
        changed_bursts = [offset for offset in burst_offsets
                          if working[offset:offset + 64] != candidate[offset:offset + 64]]
        passes.append(dict(short_scan_transaction=scan,
                           short_scan_reads=SHORT_COUNT,
                           changed_short_transactions=[scan + (offset - SHORT_START) // 4
                                                       for offset in changed_short],
                           prelude_transaction=prelude_starts[-1],
                           prelude_addresses=[f'{offset:06x}' for offset in prelude],
                           long_run_transaction=start,
                           long_run_reads=len(burst_offsets),
                           long_run_first=f'{burst_offsets[0]:06x}',
                           long_run_last=f'{burst_offsets[-1]:06x}',
                           changed_long_reads=len(changed_bursts),
                           last_changed_long_read=f'{changed_bursts[-1]:06x}'))
    if passes[0]['long_run_reads'] != passes[1]['long_run_reads']:
        raise ValueError('long pass lengths differ')
    end_offset = LONG_START + passes[0]['long_run_reads'] * 64
    changed_after_observed_run = [offset for offset in range(end_offset, len(working))
                                  if working[offset] != candidate[offset]]
    return dict(schema=1,
                changed_short_word_addresses=[f'{offset:06x}' for offset in changed_short],
                observed_long_run_end_exclusive=f'{end_offset:06x}',
                changed_bytes_after_observed_long_run=len(changed_after_observed_run),
                last_changed_byte_after_observed_long_run=(
                    f'{changed_after_observed_run[-1]:06x}' if changed_after_observed_run else None),
                trace_contains_lengths=False,
                candidate_may_change_future_read_sequence=True,
                passes=passes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--working-rom', type=Path, required=True)
    parser.add_argument('--candidate-rom', type=Path, required=True)
    parser.add_argument('--candidate-sha256', choices=(CANDIDATE_SHA256, SAME_LENGTH_SHA256),
                        default=CANDIDATE_SHA256)
    parser.add_argument('--trace', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if 'output' not in args.output.parts or args.output.exists():
        parser.error('output must be a new private file under output/')
    working = pinned_rom(args.working_rom, WORKING_SHA256)
    candidate = pinned_rom(args.candidate_rom, args.candidate_sha256)
    result = dict(schema=1, working_sha256=WORKING_SHA256,
                  candidate_sha256=args.candidate_sha256, traces=[])
    for trace in args.trace:
        metadata = json.loads(trace.with_suffix('.json').read_text())
        commands = expand(trace.read_bytes(), metadata)
        result['traces'].append(dict(trace_sha256=metadata['binary_sha256'],
                                     commands=len(commands),
                                     **coverage(commands, working, candidate)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    args.output.chmod(0o600)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
