#!/usr/bin/env python3
"""Replay a preselected CS router against physical BC250 SPI edges.

Digital model only: the selector FIFO is prefilled, the flash CS output is
ideal, and Pico clock/voltage, pad delay, wiring and contention are unmeasured.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from capture import decode, unpack, private_write
from router_model import SM


def assemble(executable):
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / 'select.json'
        subprocess.run([executable, '-o', 'json',
                        str(Path(__file__).with_name('cs_select.pio')), str(output)],
                       check=True)
        return json.loads(output.read_text())['programs'][0]


def replay(blob, rom, program, system_hz, *, start_index, patch_index=2,
           commands=6, sync_cycles=2, phase_fifths=0):
    meta, data = unpack(blob)
    if meta['flags'] or len(rom) != 0x1000000 or system_hz < meta['sample_hz']:
        raise ValueError('unflagged trace, full ROM and adequate model clock required')
    if not 0 <= patch_index < commands or sync_cycles not in (2, 3) or not 0 <= phase_fifths < 5:
        raise ValueError('invalid model case')
    tx = [t for t in decode(blob, rom)['transactions'] if t['complete']][start_index:start_index+commands]
    if len(tx) != commands or any(t.get('opcode') != 3 or t['clocks'] != 64 or
           t.get('rom_match') is not True or t['idle_clock'] != 0 for t in tx):
        raise ValueError('expected six complete clean-ROM mode-0 READ03 transactions')
    high_before = tx[0]['cs_high_before_samples']
    if high_before is None or high_before < 8:
        raise ValueError('need a measured idle gap before the first transaction')
    samples = [n for byte in data for n in (byte & 15, byte >> 4)]
    start = tx[0]['start_sample'] - min(50, high_before - 1)
    end = tx[-1]['end_sample']
    sm = SM(program, collections.deque(int(i == patch_index) for i in range(commands)))
    pipe = collections.deque([4] * sync_cycles)
    flash_cs = 1
    last_select_cycle = None
    cycle = 0
    prev_pins = 4
    checked = [0] * commands
    setup_cycles = []
    errors = []
    timebase = 5 * meta['clock_hz']
    quantum = 5 * system_hz * meta['divider']
    for i, sample in enumerate(samples[start:end]):
        absolute = i + start
        pins = (sample << 2) & 0x1c
        if not pins & 4 and pins & 8 and not prev_pins & 8:
            for index, transaction in enumerate(tx):
                if transaction['start_sample'] <= absolute < transaction['end_sample']:
                    checked[index] += 1
                    expected = int(index != patch_index)  # 1 means the flash must be selected
                    selected = int(flash_cs == 0)
                    if selected != expected:
                        errors.append(dict(row=index, clock=checked[index],
                                           expected_selected=expected, actual_selected=selected))
                    if checked[index] == 1 and expected and last_select_cycle is not None:
                        setup_cycles.append(cycle - last_select_cycle)
                    break
        steps = (((i + 1) * quantum + phase_fifths * meta['clock_hz']) // timebase
                 - (i * quantum + phase_fifths * meta['clock_hz']) // timebase)
        for _ in range(steps):
            pipe.append(pins)
            changes = sm.step(pipe.popleft(), set())
            if 'flash_cs' in changes:
                if flash_cs and not changes['flash_cs']:
                    last_select_cycle = cycle
                flash_cs = changes['flash_cs']
            cycle += 1
        prev_pins = pins
    if checked != [64] * commands:
        errors.append(dict(error='incomplete rising-edge sequence', counts=checked))
    # The data sheet specifies at least 3 ns of flash CS setup before SCLK.
    min_setup_ns = min(setup_cycles, default=0) * 1e9 / system_hz
    if len(setup_cycles) != commands - 1 or min_setup_ns < 3:
        errors.append(dict(error='modeled CS setup below 3 ns or missing',
                           setup_ns=min_setup_ns, measured_rows=len(setup_cycles)))
    return dict(model_only=True, physical_timing_qualified=False,
                system_clock_hz=system_hz, sync_cycles=sync_cycles,
                phase_fifths=phase_fifths, patch_index=patch_index,
                patch_address=f'{tx[patch_index]["address"]:06x}',
                minimum_modeled_flash_cs_setup_ns=min_setup_ns,
                pass_model=not errors, errors=errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--pioasm', required=True)
    parser.add_argument('--target-address', type=lambda value: int(value, 0), required=True)
    parser.add_argument('--clock-hz', type=int, default=200000000)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    program = assemble(args.pioasm)
    blob, rom = args.capture.read_bytes(), args.rom.read_bytes()
    tx = [t for t in decode(blob, rom)['transactions'] if t['complete']]
    found = next((i for i,t in enumerate(tx) if t.get('address') == args.target_address), None)
    if found is None or found < 2 or found + 3 >= len(tx):
        raise ValueError('target address lacks a two-before/three-after read window')
    cases = [replay(blob, rom, program, args.clock_hz, start_index=found-2,
                    sync_cycles=sync, phase_fifths=phase)
             for sync in (2, 3) for phase in range(5)]
    report = dict(schema=1, capture=str(args.capture),
                  pio_sha256=hashlib.sha256(Path(__file__).with_name('cs_select.pio').read_bytes()).hexdigest(),
                  all_cases_pass=all(case['pass_model'] for case in cases), cases=cases,
                  limitations=['FIFO route is preloaded before each transaction.',
                               'GPIO pad delay, flash input threshold and wiring are unmeasured.',
                               'Pico reply OE gating and address validation are not modeled.'])
    private_write(args.output, (json.dumps(report, indent=2) + '\n').encode())
    print(json.dumps(dict(all_cases_pass=report['all_cases_pass'],
                          minimum_modeled_flash_cs_setup_ns=min(
                              case['minimum_modeled_flash_cs_setup_ns'] for case in cases),
                          failures=[case for case in cases if not case['pass_model']]), indent=2))


if __name__ == '__main__':
    main()
