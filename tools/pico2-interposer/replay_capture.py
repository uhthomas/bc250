#!/usr/bin/env python3
"""Replay recorded host edges against the assembled router, without hardware.

Clock scaling changes modeled instruction time only. It does not establish
that a physical RP2350, SRAM, flash or USB will operate at that clock/voltage.
The trace's sample quantization and analogue uncertainty remain unchanged.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from capture import decode, private_write, unpack
from router_model import Bus, assemble


def replay(blob, rom, programs, system_hz, *, sync_cycles=2, feed_cycles=12,
           commands=6, patch_index=2, flash_release_ns=40/3):
    meta, payload = unpack(blob)
    if meta['flags'] or len(rom) != 0x1000000:
        raise ValueError('unflagged real capture and full 16 MiB ROM required')
    if system_hz < meta['sample_hz'] or not 0 <= patch_index < commands:
        raise ValueError('model clock must be >= sample clock; patch index must be in window')
    decoded = decode(blob, rom)
    tx = [t for t in decoded['transactions'] if t['complete']][:commands]
    if len(tx) != commands or any(t.get('opcode') != 3 or t['clocks'] != 64
            or t['address'] % 4 or t.get('rom_match') is not True
            or t['idle_clock'] != 0 for t in tx):
        raise ValueError('window needs complete, aligned mode-0 READ03 words matching ROM')
    # A complemented original word is a diagnostic patch only, not a BIOS patch.
    rows = [(int(t['mosi_hex'][:8],16), i == patch_index,
             int(t['data_hex'],16) ^ 0xffffffff if i == patch_index else 0)
            for i,t in enumerate(tx)]
    def original(command):
        address = command & 0xffffff
        return int.from_bytes(rom[address:address+4], 'big')
    # Chip output release is a time assumption, not a fixed number of Pico
    # cycles: overclocking the Pico does not make the external flash faster.
    release_cycles = math.ceil(flash_release_ns * system_hz / 1e9)
    bus = Bus(programs, rows, original, sync_cycles=sync_cycles,
              feed_cycles=feed_cycles, flash_release_cycles=release_cycles)
    bus.tick(4, 600)  # Prefilled FIFOs, no CPU monitor: optimistic PIO-only test.
    samples = [n for byte in payload for n in (byte & 15, byte >> 4)]
    start, end = tx[0]['start_sample'], tx[-1]['end_sample']
    for i,sample in enumerate(samples[start:end]):
        # Scale cumulative edge times rather than rounding each sample width.
        numerator = system_hz * meta['divider']
        cycles = ((i+1)*numerator // meta['clock_hz']
                  - i*numerator // meta['clock_hz'])
        bus.tick((sample << 2) & 0x1c, cycles)
    bus.tick(4, 600)
    errors = []
    for i,(command,patch,word) in enumerate(rows):
        expected = word if patch else original(command)
        try:
            got = bus.data(bus.samples[i*64:(i+1)*64])
            error = None if got == expected else f'got {got:08x}, expected {expected:08x}'
        except AssertionError as exc:
            error = str(exc)
        if error:
            errors.append(dict(row=i, command=f'{command:08x}', error=error))
    passed = (not errors and not bus.contentions and 0 not in bus.irqs
              and bus.counter.rx == [64]*commands
              and len(bus.samples) == commands*64)
    return dict(model_only=True, physical_overclock_performed=False,
        physical_timing_qualified=False, pio_replay_pass=passed,
        system_clock_hz=system_hz, sync_cycles=sync_cycles, feed_cycles=feed_cycles,
        flash_release_assumption_ns=flash_release_ns,
        flash_release_cycles=release_cycles, commands=commands, patch_index=patch_index,
        reply_errors=errors, contention_cycles=len(bus.contentions),
        irq0=0 in bus.irqs, clock_counts=bus.counter.rx,
        recorded_clock_hz=decoded['summary']['mean_clock_hz'],
        capture_warnings=decoded['summary']['warnings'],
        raw_sha256=hashlib.sha256(blob).hexdigest(),
        rom_sha256=hashlib.sha256(rom).hexdigest(),
        limitations=['Recorded sample boundaries treated as exact; analogue timing unmodeled.',
                     'Initially prefilled FIFO; CPU fault monitor and anchor search omitted.',
                     'Higher clocks modeled without asserting hardware/voltage stability.',
                     'Synthetic complemented reply, not a captured target-key substitution.'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture', type=Path)
    p.add_argument('--rom', required=True, type=Path)
    p.add_argument('--pioasm', required=True)
    p.add_argument('--clock-hz', nargs='+', type=int, default=[150000000,300000000,480000000])
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    programs = assemble(a.pioasm)
    blob,rom = a.capture.read_bytes(),a.rom.read_bytes()
    results = [replay(blob,rom,programs,hz,sync_cycles=sync,feed_cycles=feed)
               for hz in a.clock_hz for sync,feed in ((2,12),(3,128))]
    report = dict(schema=1,capture=str(a.capture),results=results)
    private_write(a.output,(json.dumps(report,indent=2)+'\n').encode())
    print(json.dumps([dict(clock_hz=r['system_clock_hz'],sync_cycles=r['sync_cycles'],
                           feed_cycles=r['feed_cycles'],passed=r['pio_replay_pass'],
                           errors=r['reply_errors']) for r in results],indent=2))


if __name__ == '__main__':
    main()
