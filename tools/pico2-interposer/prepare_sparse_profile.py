#!/usr/bin/env python3
"""Generate a dry-run-only sparse selector profile from a verified full trace.

The header contains complete READ03 command runs and public/signed patch
words, but no private signing key. It is written under ignored output/.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from analyze_full_cs_stream import analyze, expand


def compress(commands):
    runs = []
    for command in commands:
        if runs and command == runs[-1][0] + 4 * runs[-1][1]:
            runs[-1] = (runs[-1][0], runs[-1][1] + 1)
        else:
            runs.append((command, 1))
    return runs


def prepare(binary, metadata, filtered, clean, patched):
    audit = analyze(binary, metadata, filtered, clean, patched)
    commands = expand(binary, metadata)
    first = audit['first_keydb_transaction']
    scope = commands[first:first + audit['required_scope_commands']]
    runs = compress(scope)
    if len(runs) != 37 or len(scope) != 872744:
        raise ValueError('unexpected physical command profile geometry')
    second_keydb = next(i for i in range(1, len(scope) - 2) if
                        scope[i:i+3] == [0x039db038, 0x039db03c, 0x039db040]) + 2
    if second_keydb != 696:
        raise ValueError('second KEYDB read did not occur at expected relative row')
    changed = [(0x03000000 | address, int.from_bytes(patched[address:address+4], 'big'))
               for address in range(0, len(clean), 4)
               if clean[address:address+4] != patched[address:address+4]]
    if len(changed) != 318:
        raise ValueError('unexpected changed-word count')
    patch_by_command = dict(changed)
    patch_rows = [i for i, command in enumerate(scope) if
                  command in patch_by_command and not
                  (0x9dad00 <= (command & 0xffffff) < 0x9dbad0 and i >= second_keydb)]
    if len(patch_rows) != 452:
        raise ValueError(f'unexpected PATCH response count {len(patch_rows)}')
    return dict(schema=1, trace_sha256=metadata['binary_sha256'],
                scope_sha256=hashlib.sha256(b''.join(c.to_bytes(4, 'little') for c in scope)).hexdigest(),
                command_rows=len(scope), runs=runs, changed_words=changed,
                second_keydb_row=second_keydb, dryrun_patch_rows=len(patch_rows),
                board_patch_arm=False, physical_reply_tested=False)


def header(plan):
    lines = ['/* Generated from verified physical trace; dry-run only. */',
             '#ifndef BC250_SPARSE_PHYSICAL_PROFILE_H',
             '#define BC250_SPARSE_PHYSICAL_PROFILE_H',
             f'#define PROFILE_NAME "boot-rle-{plan["trace_sha256"][:12]}"',
             f'#define PROFILE_ROWS {plan["command_rows"]}u',
             f'#define PROFILE_RUNS {len(plan["runs"])}u',
             f'#define PROFILE_CHANGED_WORDS {len(plan["changed_words"])}u',
             f'#define PROFILE_SECOND_KEYDB_ROW {plan["second_keydb_row"]}u',
             f'#define PROFILE_EXPECTED_PATCH_READS {plan["dryrun_patch_rows"]}u',
             'static const struct expected_run expected_runs[PROFILE_RUNS] = {']
    lines += [f'    {{0x{start:08x}u, {count}u}},' for start, count in plan['runs']]
    lines += ['};',
              'static const struct patch_word patch_words[PROFILE_CHANGED_WORDS] = {']
    lines += [f'    {{0x{command:08x}u, 0x{reply:08x}u}},'
              for command, reply in plan['changed_words']]
    return '\n'.join(lines + ['};', '#endif', ''])


def private_write(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as file:
        file.write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--metadata', required=True, type=Path)
    parser.add_argument('--filtered', required=True, type=Path)
    parser.add_argument('--clean', required=True, type=Path)
    parser.add_argument('--patched', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    plan = prepare(args.binary.read_bytes(), json.loads(args.metadata.read_text()),
                   json.loads(args.filtered.read_text()), args.clean.read_bytes(),
                   args.patched.read_bytes())
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    private_write(args.output_dir/'sparse_physical_profile.h', header(plan))
    summary = {key: value for key, value in plan.items() if key not in ('runs', 'changed_words')}
    summary.update(run_count=len(plan['runs']), changed_word_count=len(plan['changed_words']))
    private_write(args.output_dir/'profile.json', json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
