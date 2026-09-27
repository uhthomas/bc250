#!/usr/bin/env python3
"""Derive a non-executable PASS/PATCH read-window plan from the filtered trace."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from analyze_cs_pass_hunt import analyze, ANCHOR


def runs_for_pass(hits):
    runs = []
    current = []
    for hit in hits:
        address = int(hit['command'], 16) & 0xffffff
        if current:
            previous = current[-1]
            previous_address = int(previous['command'], 16) & 0xffffff
            if (hit['transaction'] != previous['transaction'] + 1 or
                    address != previous_address + 4):
                runs.append(current)
                current = []
        current.append(hit)
    if current:
        runs.append(current)
    return runs


def plan(capture, clean, patched):
    audit = analyze(capture, clean, patched)
    hits = capture['hits']
    anchors = [i for i, hit in enumerate(hits) if
               tuple(hit[key] for key in ('command', 'previous', 'previous2')) == ANCHOR]
    length = anchors[2] - anchors[0]
    a = hits[anchors[0]:anchors[2]]
    b = hits[anchors[2]:anchors[2] + length]
    changed = {address for address in range(0, len(clean), 4)
               if clean[address:address + 4] != patched[address:address + 4]}
    first_runs, second_runs = runs_for_pass(a), runs_for_pass(b)
    if len(first_runs) != len(second_runs):
        raise ValueError('the repeated passes have different run counts')
    keydb_run = 0
    windows = []
    required = 0
    for index, (first, second) in enumerate(zip(first_runs, second_runs)):
        addrs = [int(hit['command'], 16) & 0xffffff for hit in first]
        if addrs != [int(hit['command'], 16) & 0xffffff for hit in second]:
            raise ValueError('the repeated passes have different run addresses')
        in_type50 = 0x9dad00 <= addrs[0] < 0x9dbad0
        if in_type50:
            keydb_run += 1
        patch = [address for address in addrs if address in changed and
                 (not in_type50 or keydb_run == 1)]
        required += len(patch)
        windows.append(dict(index=index, start=f'{addrs[0]:06x}',
                            end_inclusive=f'{addrs[-1]:06x}', reads=len(addrs),
                            first_transaction=first[0]['transaction'],
                            second_transaction=second[0]['transaction'],
                            entry_previous=first[0]['previous'],
                            entry_previous2=first[0]['previous2'],
                            policy=('type50-copy-patch' if in_type50 and keydb_run == 1
                                    else 'type50-verification-clean' if in_type50
                                    else 'patch-changed-words' if patch else 'pass'),
                            patch_reads=len(patch),
                            patch_first=f'{patch[0]:06x}' if patch else None,
                            patch_last=f'{patch[-1]:06x}' if patch else None))
    if keydb_run != 2 or required != 452:
        raise ValueError(f'unexpected KEYDB read count or PATCH response count: {keydb_run}, {required}')
    next_for_context = defaultdict(set)
    for hit in a:
        address = int(hit['command'], 16) & 0xffffff
        if address in changed:
            next_for_context[(hit['previous2'], hit['previous'])].add(hit['command'])
    ambiguous = [dict(previous2=pair[0], previous=pair[1],
                      observed_next=sorted(values))
                 for pair, values in sorted(next_for_context.items()) if len(values) > 1]
    return dict(schema=1, source='filtered physical READ03 commands',
                audit=audit, windows=windows, windows_per_pass=len(windows),
                planned_patch_responses_per_pass=required,
                ambiguous_predecessor_contexts=ambiguous,
                first_type50_read_is_copy_in_native_loader_model=True,
                unrecorded_commands_unverified=True,
                live_route_latency_unmeasured=True,
                board_patch_profile_ready=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', required=True, type=Path)
    parser.add_argument('--clean', required=True, type=Path)
    parser.add_argument('--patched', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = plan(json.loads(args.capture.read_text()),
                  args.clean.read_bytes(), args.patched.read_bytes())
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(windows_per_pass=result['windows_per_pass'],
                          planned_patch_responses_per_pass=result['planned_patch_responses_per_pass'],
                          patch_windows=[dict(index=w['index'], start=w['start'],
                                              patch_reads=w['patch_reads'], policy=w['policy'])
                                         for w in result['windows'] if w['patch_reads']]), indent=2))


if __name__ == '__main__':
    main()
