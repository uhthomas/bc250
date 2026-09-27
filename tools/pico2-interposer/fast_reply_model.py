#!/usr/bin/env python3
"""Exercise an isolated preselected MISO engine against recorded SPI edges.

This models assembled PIO instructions only. It assumes that a separate,
as-yet-unimplemented selector has already deselected the stock flash, and
that expected replies have reached the Pico FIFO. It cannot approve a board
connection or a physical Pico overclock.
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


def assemble(executable):
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / 'fast_reply.json'
        subprocess.run([executable, '-o', 'json', str(Path(__file__).with_name('fast_reply.pio')),
                        str(output)], check=True)
        return json.loads(output.read_text())['programs'][0]


def replay(blob, rom, program, system_hz, *, sync_cycles=2,
           phase_fifths=0, commands=6, patch_index=2, start_index=0):
    meta, data = unpack(blob)
    if meta['flags'] or len(rom) != 0x1000000:
        raise ValueError('unflagged physical capture and full 16 MiB ROM required')
    if system_hz < meta['sample_hz'] or not 0 <= patch_index < commands:
        raise ValueError('model clock must cover sample clock; patch index must be in window')
    if not 0 <= phase_fifths < 5 or sync_cycles not in (2,3):
        raise ValueError('phase must be 0..4 fifths; synchronization 2 or 3 cycles')
    decoded = decode(blob, rom)
    tx = [t for t in decoded['transactions'] if t['complete']][start_index:start_index+commands]
    if len(tx) != commands or any(t.get('opcode') != 3 or t['clocks'] != 64
            or t['address'] % 4 or t.get('rom_match') is not True
            or t['idle_clock'] != 0 for t in tx):
        raise ValueError('expected complete aligned mode-0 four-byte READ03 sequence')
    replies = [int(t['data_hex'],16) ^ (0xffffffff if i == patch_index else 0)
               for i,t in enumerate(tx)]
    # Software prefill is deliberately optimistic: a later hardware design
    # must prove DMA/CPU FIFO service under the recorded 353 ns CS gaps.
    sm = SM(program, collections.deque(replies))
    pipe = collections.deque([4]*sync_cycles)
    state = dict(oe=0, data=0)
    rises = [[] for _ in tx]
    samples = [n for byte in data for n in (byte & 15, byte >> 4)]
    start,end = tx[0]['start_sample'],tx[-1]['end_sample']
    old_pins = 4
    timebase = 5*meta['clock_hz']
    quantum = 5*system_hz*meta['divider']
    for i,sample in enumerate(samples[start:end]):
        pins = (sample << 2) & 0x1c
        steps = (((i+1)*quantum + phase_fifths*meta['clock_hz']) // timebase
                 - (i*quantum + phase_fifths*meta['clock_hz']) // timebase)
        for _ in range(steps):
            if not pins & 4 and pins & 8 and not old_pins & 8:
                for index,t in enumerate(tx):
                    if t['start_sample'] <= i+start < t['end_sample']:
                        rises[index].append((state['oe'],state['data']))
                        break
            pipe.append(pins)
            state.update(sm.step(pipe.popleft(),set()))
            old_pins = pins
    errors=[]
    for index,(edges,expected) in enumerate(zip(rises,replies)):
        if len(edges)!=64:
            errors.append(dict(row=index,error=f'{len(edges)} clock edges, expected 64'))
            continue
        bits=edges[32:]
        got=sum(bit<<(31-i) for i,(oe,bit) in enumerate(bits))
        missing=sum(not oe for oe,_ in bits)
        if missing or got!=expected:
            errors.append(dict(row=index,missing_output_edges=missing,
                               got=f'{got:08x}',expected=f'{expected:08x}'))
    return dict(model_only=True,physical_overclock_performed=False,
        physical_timing_qualified=False,standalone_reply_pass=not errors,
        system_clock_hz=system_hz,recorded_clock_hz=decoded['summary']['mean_clock_hz'],
        sync_cycles=sync_cycles,phase_fifths=phase_fifths,
        commands=commands,patch_index=patch_index,start_index=start_index,
        patch_address=f'{tx[patch_index]["address"]:06x}',reply_errors=errors,
        raw_sha256=hashlib.sha256(blob).hexdigest(),
        rom_sha256=hashlib.sha256(rom).hexdigest(),
        limitations=['Stock flash is assumed deselected for every modeled transaction.',
                     'Full address check, CS selector and fault/abort path are absent.',
                     'FIFO words are preloaded; hardware throughput is unmeasured.',
                     'PIO waveform is digital; analogue timing and clock stability unmeasured.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture',type=Path)
    parser.add_argument('--rom',required=True,type=Path)
    parser.add_argument('--pioasm',required=True)
    parser.add_argument('--clock-hz',type=int,default=480000000)
    parser.add_argument('--target-address',type=lambda value: int(value,0),
                        help='model six reads centered on the first occurrence of this address')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    program=assemble(args.pioasm)
    blob,rom=args.capture.read_bytes(),args.rom.read_bytes()
    start_index=0
    if args.target_address is not None:
        decoded=decode(blob,rom)
        tx=[t for t in decoded['transactions'] if t['complete']]
        found=next((i for i,t in enumerate(tx) if t.get('address')==args.target_address),None)
        if found is None or found < 2 or found+3 >= len(tx):
            raise ValueError('target address lacks a two-before/three-after complete-read window')
        start_index=found-2
    cases=[replay(blob,rom,program,args.clock_hz,sync_cycles=sync,
                  phase_fifths=phase,start_index=start_index)
           for sync in (2,3) for phase in range(5)]
    report=dict(schema=1,capture=str(args.capture),target_address=(
        f'{args.target_address:06x}' if args.target_address is not None else None),
        pio_sha256=hashlib.sha256(
        Path(__file__).with_name('fast_reply.pio').read_bytes()).hexdigest(),
        all_cases_pass=all(c['standalone_reply_pass'] for c in cases),cases=cases)
    private_write(args.output,(json.dumps(report,indent=2)+'\n').encode())
    print(json.dumps(dict(all_cases_pass=report['all_cases_pass'],
                          failures=[dict(sync_cycles=c['sync_cycles'],
                                         phase_fifths=c['phase_fifths'],errors=c['reply_errors'])
                                    for c in cases if not c['standalone_reply_pass']]),indent=2))


if __name__=='__main__':
    main()
