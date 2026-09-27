#!/usr/bin/env python3
"""Replay the assembled open-drain CS PIO against real passive captures.

Digital timing only: GPIO pad delay, pull-up RC, wire length and analogue
thresholds are not represented. The resulting margin is an upper bound.
"""
import argparse
import collections
import json
from pathlib import Path

from capture import decode, unpack
from fast_select_model import assemble
from router_model import SM


def replay(blob, program, system_hz, *, sync_cycles=2, phase_fifths=0):
    meta, data = unpack(blob)
    if meta['flags'] or system_hz < meta['sample_hz']:
        raise ValueError('clean capture and model clock >= sample rate required')
    transactions = decode(blob)['transactions']
    complete = [t for t in transactions if t['complete'] and t['idle_clock'] == 0]
    if not complete:
        raise ValueError('no complete mode-0 transactions')
    # Exercise minimum measured setup/gap and their neighbours, not just a
    # synthetic square wave. A fresh PIO SM begins in the preceding idle gap.
    chosen = sorted(complete, key=lambda t: t['cs_setup_samples'] or 999)[:16]
    chosen += sorted(complete, key=lambda t: t['cs_high_before_samples'] or 999)[:16]
    samples = [n for byte in data for n in (byte & 15, byte >> 4)]
    minimum_setup = float('inf')
    minimum_release = float('inf')
    failures = []
    timebase = 5 * meta['clock_hz']
    quantum = 5 * system_hz * meta['divider']
    for tx in chosen:
        begin = max(0, tx['start_sample'] - min(25, tx['cs_high_before_samples'] or 0))
        successor = next((t for t in complete if t['start_sample'] > tx['start_sample']), None)
        end = min(len(samples), (successor or tx)['end_sample'] + 25)
        sm = SM(program)
        pipe = collections.deque([4] * sync_cycles)
        selected = False
        last_low = None
        last_high = None
        previous = 4
        cycle = 0
        first_rise = False
        for sample_index in range(begin, end):
            pins = (samples[sample_index] << 2) & 0x1c
            i = sample_index - begin
            steps = (((i + 1) * quantum + phase_fifths * meta['clock_hz']) // timebase
                     - (i * quantum + phase_fifths * meta['clock_hz']) // timebase)
            for _ in range(steps):
                if not first_rise and not (pins & 4) and (pins & 8) and not (previous & 8):
                    first_rise = True
                    if not selected or last_low is None:
                        failures.append('flash CS# not low at first clock')
                    else:
                        minimum_setup = min(minimum_setup, (cycle - last_low) * 1e9 / system_hz)
                pipe.append(pins)
                change = sm.step(pipe.popleft(), set())
                if 'flash_cs' in change:
                    if selected and change['flash_cs']:
                        selected = False
                        last_high = cycle
                    elif not selected and not change['flash_cs']:
                        selected = True
                        last_low = cycle
                        if last_high is not None:
                            minimum_release = min(minimum_release,
                                                  (cycle - last_high) * 1e9 / system_hz)
                previous = pins
                cycle += 1
        if not first_rise:
            failures.append('first clock not seen')
        if selected:
            failures.append('flash CS# not released after transaction')
    return dict(system_hz=system_hz, sync_cycles=sync_cycles,
                phase_fifths=phase_fifths, windows=len(chosen),
                min_digital_setup_ns=minimum_setup,
                min_digital_release_ns=minimum_release,
                failures=failures)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('capture', type=Path)
    parser.add_argument('--pioasm', required=True)
    parser.add_argument('--clock', type=int, nargs='+', default=[150000000, 200000000])
    args = parser.parse_args()
    program = assemble(args.pioasm, 'cs_open_drain.pio')
    blob = args.capture.read_bytes()
    rows = [replay(blob, program, hz, sync_cycles=sync, phase_fifths=phase)
            for hz in args.clock for sync in (2, 3) for phase in range(5)]
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
