#!/usr/bin/env python3
"""Check whether passive raw traces include every word changed by a ROM overlay.

Coverage means a clean word was observed on the bus at least once. It does not
establish that every later pass, handover, or active reply has been tested.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def contiguous_runs(addresses):
    runs = []
    for address in sorted(addresses):
        if not runs or address != runs[-1][-1] + 4:
            runs.append([])
        runs[-1].append(address)
    return [dict(first=f'{run[0]:06x}', last=f'{run[-1]:06x}', words=len(run))
            for run in runs]


def analyze(clean_path, patched_path, manifest_path, traces):
    clean, patched = clean_path.read_bytes(), patched_path.read_bytes()
    if len(clean) != len(patched) or len(clean) != 0x1000000:
        raise ValueError('expected two 16 MiB ROMs')
    manifest = json.loads(manifest_path.read_text())
    clean_sha = hashlib.sha256(clean).hexdigest()
    patched_sha = hashlib.sha256(patched).hexdigest()
    if clean_sha != manifest['clean_sha256'] or patched_sha != manifest['patched_sha256']:
        raise ValueError('ROM hashes do not match the retained manifest')
    ranges = {
        'type50': tuple(int(x, 16) for x in manifest['type50_modulus_flash_range']),
        'tos': tuple(int(x, 16) for x in manifest['tos_flash_range']),
        'driver': tuple(int(x, 16) for x in manifest['driver_flash_range']),
    }
    changed = {i for i in range(0, len(clean), 4) if clean[i:i+4] != patched[i:i+4]}
    if any(sum(start <= address < end for start, end in ranges.values()) != 1
           for address in changed):
        raise ValueError('a changed word is outside or ambiguously inside the expected regions')

    counts = Counter()
    trace_reports = []
    for path in traces:
        report = json.loads(path.read_text())
        summary = report['summary']
        if (summary['flags'] != 0 or summary['rom_mismatches'] != 0 or
                not summary['rom_compared']):
            raise ValueError(f'{path}: discontinuity or missing ROM comparison')
        addresses = []
        for transaction in report['transactions']:
            if not transaction['complete'] or transaction.get('opcode') != 3:
                continue
            if transaction['clocks'] != 64 or transaction.get('rom_match') is not True:
                raise ValueError(f'{path}: unsupported or mismatching complete read')
            address = transaction['address']
            if address in changed:
                addresses.append(address)
                counts[address] += 1
        trace_reports.append(dict(path=str(path), crc32=summary['crc32'],
                                  reads=summary['read03_transactions'],
                                  changed_word_reads=len(addresses),
                                  changed_unique_words=len(set(addresses)),
                                  mean_clock_hz=summary['mean_clock_hz'],
                                  sampled_edge_ambiguities=summary['sampled_edge_ambiguities']))

    regions = {}
    for name, (start, end) in ranges.items():
        needed = {address for address in changed if start <= address < end}
        seen = needed & counts.keys()
        regions[name] = dict(changed_words=len(needed), seen_words=len(seen),
                             missing_runs=contiguous_runs(needed - seen),
                             changed_runs=contiguous_runs(needed),
                             observed_instances=sum(counts[address] for address in needed))
    return dict(schema=1, clean_sha256=clean_sha, patched_sha256=patched_sha,
                changed_bytes=sum(a != b for a, b in zip(clean, patched)),
                changed_words=len(changed), seen_changed_words=len(changed & counts.keys()),
                all_changed_words_seen=changed <= counts.keys(),
                every_read_matched_clean_rom=True,
                every_boot_pass_covered=False,
                active_handover_tested=False,
                regions=regions, traces=trace_reports)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', type=Path, required=True)
    parser.add_argument('--patched', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('traces', nargs='+', type=Path)
    args = parser.parse_args()
    report = analyze(args.clean, args.patched, args.manifest, args.traces)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in
                      ('changed_bytes', 'changed_words', 'seen_changed_words',
                       'all_changed_words_seen')}, indent=2))


if __name__ == '__main__':
    main()
