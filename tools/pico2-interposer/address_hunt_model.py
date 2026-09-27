#!/usr/bin/env python3
"""Check the assembled input-only address sniffer against recorded bus edges."""
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
        output=Path(directory)/'address_hunt.json'
        subprocess.run([executable,'-o','json',
                        str(Path(__file__).with_name('address_hunt.pio')),str(output)],check=True)
        program=json.loads(output.read_text())['programs'][0]
    for entry in program['instructions']:
        word=int(entry['hex'],16)
        if word>>13 == 3 or (word>>13 == 7 and (word>>5)&7 != 1) or word&0x1000:
            raise ValueError('address hunter contains a PIO output instruction')
    return program


def replay(blob, rom, program, *, commands=6, sync_cycles=2):
    meta,data=unpack(blob)
    if meta['flags'] or len(rom)!=0x1000000 or sync_cycles not in (2,3):
        raise ValueError('unflagged capture, 16 MiB ROM and 2/3-cycle sync required')
    decoded=decode(blob,rom)
    tx=[t for t in decoded['transactions'] if t['complete']][:commands]
    if len(tx)!=commands or any(t.get('opcode')!=3 or t['clocks']!=64 or
            t.get('rom_match') is not True for t in tx):
        raise ValueError('expected complete ROM-matching READ03 sequence')
    samples=[n for byte in data for n in (byte&15,byte>>4)]
    # Start during observed CS-high time, so the PIO's initial WAIT 1 CS
    # and WAIT 0 CS each see their actual idle/selection state.
    begin=tx[0]['start_sample']
    while begin>0 and tx[0]['start_sample']-begin<24 and samples[begin-1]&1:
        begin-=1
    if begin==tx[0]['start_sample']:
        raise ValueError('no measured idle CS before first complete transaction')
    end=tx[-1]['end_sample']
    sm=SM(program,in_autopush=True)
    pipe=collections.deque([4]*sync_cycles)
    for sample in samples[begin:end]:
        pipe.append((sample<<2)&0x1c)
        sm.step(pipe.popleft(),set())
    expected=[int(t['mosi_hex'][:8],16) for t in tx]
    got=sm.rx
    return dict(model_only=True,physical_hunt_test_performed=False,
        PIO_outputs_present=False,matched=got==expected,
        sync_cycles=sync_cycles,clock_hz=meta['clock_hz'],
        commands=commands,expected_commands=[f'{c:08x}' for c in expected],
        captured_commands=[f'{c:08x}' for c in got],
        raw_sha256=hashlib.sha256(blob).hexdigest(),
        limitations=['Sampled digital input only; CPU FIFO drain and physical wire timing unmeasured.',
                     'The model reuses a sampled waveform, so analogue input margin is unknown.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture',type=Path)
    parser.add_argument('--rom',required=True,type=Path)
    parser.add_argument('--pioasm',required=True)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    program=assemble(args.pioasm)
    blob,rom=args.capture.read_bytes(),args.rom.read_bytes()
    cases=[replay(blob,rom,program,sync_cycles=sync) for sync in (2,3)]
    report=dict(schema=1,capture=str(args.capture),
        pio_sha256=hashlib.sha256(Path(__file__).with_name('address_hunt.pio').read_bytes()).hexdigest(),
        all_cases_pass=all(c['matched'] for c in cases),cases=cases)
    private_write(args.output,(json.dumps(report,indent=2)+'\n').encode())
    print(json.dumps(dict(all_cases_pass=report['all_cases_pass'],
                          cases=[dict(sync_cycles=c['sync_cycles'],matched=c['matched'],
                                      commands=len(c['captured_commands'])) for c in cases]),indent=2))


if __name__=='__main__':
    main()
