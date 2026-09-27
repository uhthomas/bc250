#!/usr/bin/env python3
"""Replay the isolated PASS/PATCH PIO against captured SPI edges.

This is a digital model with FIFO words available before each transaction.
It does not measure pad delay, analogue handover or DMA service on hardware.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from capture import decode, private_write, unpack
from router_model import SM


def assemble(executable, program_name='fast_select.pio'):
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / 'fast_select.json'
        subprocess.run([executable, '-o', 'json',
                        str(Path(__file__).with_name(program_name)),
                        str(output)], check=True)
        return json.loads(output.read_text())['programs'][0]


def replay(blob, rom, program, system_hz, *, start_index=0, commands=6,
           patch_index=2, sync_cycles=2, phase_fifths=0, guarded=False,
           corrupt_expected_patch=False):
    meta, data = unpack(blob)
    if meta['flags'] or len(rom) != 0x1000000 or system_hz < meta['sample_hz']:
        raise ValueError('unflagged physical trace, full ROM and adequate model clock required')
    if not 0 <= patch_index < commands or sync_cycles not in (2, 3) or not 0 <= phase_fifths < 5:
        raise ValueError('invalid model case')
    tx = [t for t in decode(blob, rom)['transactions'] if t['complete']][start_index:start_index+commands]
    if len(tx) != commands or any(t.get('opcode') != 3 or t['clocks'] != 64 or
           t.get('rom_match') is not True or t['idle_clock'] != 0 for t in tx):
        raise ValueError('expected complete clean-ROM mode-0 four-byte READ03 sequence')
    high_before = tx[0]['cs_high_before_samples']
    if high_before is None or high_before < 8:
        raise ValueError('need an observed idle gap before the first transaction')

    replies = [int(t['data_hex'], 16) ^ (0xffffffff if i == patch_index else 0)
               for i, t in enumerate(tx)]
    if corrupt_expected_patch and not guarded:
        raise ValueError('expected-command corruption requires guarded program')
    fifo = collections.deque(
        word for i, (transaction, reply) in enumerate(zip(tx, replies))
        for word in ((int(i == patch_index),
                      (transaction['opcode'] << 24) | transaction['address'] |
                      int(corrupt_expected_patch and i == patch_index), reply)
                     if guarded else (int(i == patch_index), reply)))
    sm = SM(program, fifo)
    irqs = set()
    pipe = collections.deque([4] * sync_cycles)
    state = dict(flash_cs=1, oe=0, data=0)
    rises = [[] for _ in tx]
    setup_cycles = []
    errors = []
    samples = [n for byte in data for n in (byte & 15, byte >> 4)]
    start = tx[0]['start_sample'] - min(50, high_before - 1)
    end = tx[-1]['end_sample']
    previous = 4
    last_select_cycle = None
    cycle = 0
    timebase = 5 * meta['clock_hz']
    quantum = 5 * system_hz * meta['divider']
    for i, sample in enumerate(samples[start:end]):
        absolute = i + start
        pins = (sample << 2) & 0x1c
        steps = (((i + 1) * quantum + phase_fifths * meta['clock_hz']) // timebase
                 - (i * quantum + phase_fifths * meta['clock_hz']) // timebase)
        for _ in range(steps):
            if state['oe'] and state['flash_cs'] == 0:
                errors.append(dict(error='overlapping Pico and flash outputs', cycle=cycle))
                return dict(pass_model=False, errors=errors)
            if not pins & 4 and pins & 8 and not previous & 8:
                for index, transaction in enumerate(tx):
                    if transaction['start_sample'] <= absolute < transaction['end_sample']:
                        rises[index].append((state['flash_cs'], state['oe'], state['data']))
                        if (len(rises[index]) == 1 and index != patch_index and
                                not (corrupt_expected_patch and index > patch_index)):
                            if last_select_cycle is None:
                                errors.append(dict(row=index, error='flash not selected before first clock'))
                            else:
                                setup_cycles.append(cycle - last_select_cycle)
                        break
            pipe.append(pins)
            change = sm.step(pipe.popleft(), irqs)
            if 'flash_cs' in change and state['flash_cs'] and not change['flash_cs']:
                last_select_cycle = cycle
            state.update(change)
            previous = pins
            cycle += 1

    for index, (edges, expected) in enumerate(zip(rises, replies)):
        if len(edges) != 64:
            errors.append(dict(row=index, error=f'{len(edges)} clocks; expected 64'))
            continue
        selected = index != patch_index and not (corrupt_expected_patch and index > patch_index)
        wrong_route = [clock for clock, (flash_cs, oe, _) in enumerate(edges, 1)
                       if bool(flash_cs == 0) != selected or (selected and oe)]
        if wrong_route:
            errors.append(dict(row=index, error='wrong CS route or PASS MISO enabled',
                               first_clock=wrong_route[0]))
        if not selected and not corrupt_expected_patch:
            bits = edges[32:]
            missing = sum(not oe for _, oe, _ in bits)
            actual = sum(bit << (31 - offset)
                         for offset, (_, _, bit) in enumerate(bits))
            if missing or actual != expected:
                errors.append(dict(row=index, error='wrong PATCH reply',
                                   missing_output_edges=missing,
                                   actual=f'{actual:08x}', expected=f'{expected:08x}'))
        elif not selected and corrupt_expected_patch:
            if any(oe for _, oe, _ in edges) or 0 not in irqs:
                errors.append(dict(row=index, error='guard failed to suppress wrong command'))
    minimum_setup_ns = min(setup_cycles, default=0) * 1e9 / system_hz
    expected_pass_rows = patch_index if corrupt_expected_patch else commands - 1
    if len(setup_cycles) != expected_pass_rows or minimum_setup_ns < 3:
        errors.append(dict(error='flash CS setup missing or below 3 ns',
                           measured_pass_rows=len(setup_cycles),
                           minimum_setup_ns=minimum_setup_ns))
    return dict(model_only=True, pass_model=not errors, errors=errors,
                system_clock_hz=system_hz, sync_cycles=sync_cycles,
                phase_fifths=phase_fifths, patch_index=patch_index,
                guarded=guarded, corrupt_expected_patch=corrupt_expected_patch,
                fault_irq_raised=0 in irqs,
                patch_address=f'{tx[patch_index]["address"]:06x}',
                minimum_modeled_flash_cs_setup_ns=minimum_setup_ns,
                physical_timing_qualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--rom', required=True, type=Path)
    parser.add_argument('--pioasm', required=True)
    parser.add_argument('--clock-hz', type=int, default=200000000)
    parser.add_argument('--target-address', type=lambda value: int(value, 0), required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    program = assemble(args.pioasm)
    blob, rom = args.capture.read_bytes(), args.rom.read_bytes()
    complete = [t for t in decode(blob, rom)['transactions'] if t['complete']]
    found = next((i for i, t in enumerate(complete)
                  if t.get('address') == args.target_address), None)
    if found is None or found < 2 or found + 3 >= len(complete):
        raise ValueError('target address lacks a two-before/three-after window')
    cases = [replay(blob, rom, program, args.clock_hz, start_index=found - 2,
                    sync_cycles=sync, phase_fifths=phase)
             for sync in (2, 3) for phase in range(5)]
    report = dict(schema=1, capture=str(args.capture),
                  pio_sha256=hashlib.sha256(Path(__file__).with_name('fast_select.pio').read_bytes()).hexdigest(),
                  all_cases_pass=all(case['pass_model'] for case in cases),
                  cases=cases,
                  limitations=['Route/reply FIFO words are assumed available before CS falls.',
                               'No command/address check or runtime fault path is modeled.',
                               'GPIO pad delay and physical flash release are unmeasured.'])
    private_write(args.output, (json.dumps(report, indent=2) + '\n').encode())
    print(json.dumps(dict(all_cases_pass=report['all_cases_pass'],
                          failures=[case for case in cases if not case['pass_model']]), indent=2))


if __name__ == '__main__':
    main()
