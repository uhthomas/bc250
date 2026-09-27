#!/usr/bin/env python3
"""Compare repeated passive captures and screen a window for the current router.

Read-only, no GPIO access. A passing report is a digital screening result, not
permission to arm the BC250: anchor/copy identity, full-window coverage and
physical CS/MISO/CPU timing remain separate requirements. Raw captures are
re-decoded against the retained ROM; edited decode JSON is never trusted.
"""
import argparse
import hashlib
import json
from pathlib import Path
from capture import decode, private_write

LIMITS_NS = dict(cs_setup_samples=100, cs_high_before_samples=1000,
                 min_period_samples=200, min_half_period_samples=100)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def qualify(blobs, rom, *, commands=None):
    if len(blobs)<2:
        raise ValueError('at least two independently collected captures are required')
    if len(rom)!=0x1000000:
        raise ValueError('expected the full 16 MiB working ROM')
    decoded=[decode(blob,rom) for blob in blobs]
    if len({d['summary']['skip'] for d in decoded})!=1:
        raise ValueError('repeat captures must use the same --skip value')
    complete=[[t for t in d['transactions'] if t['complete']] for d in decoded]
    common=min(map(len,complete))
    if commands is None:
        commands=common
    if commands<2 or commands>common:
        raise ValueError('at least two complete reads, present in every capture, are required')
    reasons=[]
    # The first triggered transaction is normally leading-partial because PIO
    # starts sampling after CS falls. Never silently align different offsets.
    offsets=[next(i for i,t in enumerate(d['transactions']) if t['complete']) for d in decoded]
    if len(set(offsets))!=1:
        reasons.append('captures begin at different transaction boundaries')
    def signature(t):
        return (t['clocks'],t['mosi_hex'][:8],t.get('data_hex'))
    reference=[signature(t) for t in complete[0][:commands]]
    for i,rows in enumerate(complete):
        if [signature(t) for t in rows[:commands]]!=reference:
            reasons.append(f'capture {i+1}: read order, length or bytes differ')
    observations=[]
    for i,(blob,d,rows) in enumerate(zip(blobs,decoded,complete)):
        summary=d['summary']
        reasons.extend(f'capture {i+1}: {w}' for w in summary['warnings'])
        metrics={key:[] for key in (*LIMITS_NS,'cs_hold_samples')}
        unknown={key:0 for key in metrics}
        invalid=[]
        for index,t in enumerate(rows[:commands]):
            if (t.get('opcode')!=3 or t['clocks']!=64 or
                    t.get('address',1)%4 or len(t.get('data_hex',''))!=8):
                invalid.append(index)
            if t.get('rom_match') is not True:
                reasons.append(f'capture {i+1}, read {index}: original ROM bytes not verified')
            if t['idle_clock']!=0:
                reasons.append(f'capture {i+1}, read {index}: mode-0 idle clock not observed')
            for key in metrics:
                value=t[key]
                if value is None:
                    unknown[key]+=1
                else:
                    # Conservative for one-sample quantization of two edges.
                    metrics[key].append(max(0,value-1)*1e9/summary['sample_hz'])
        if invalid:
            reasons.append(f'capture {i+1}: unsupported transactions at indices {invalid[:8]}')
        minima={key:min(values) if values else None for key,values in metrics.items()}
        for key,limit in LIMITS_NS.items():
            if minima[key] is not None and minima[key]+1e-9<limit:
                reasons.append(f'capture {i+1}: {key} lower bound {minima[key]:.3f} ns < {limit} ns')
            # The first CS-high gap may precede capture start. Other unknown
            # timing fields must not be silently omitted from the minimum.
            allowed=1 if key=='cs_high_before_samples' and rows[0][key] is None else 0
            if unknown[key]>allowed:
                reasons.append(f'capture {i+1}: missing {key} measurements')
        observations.append(dict(raw_sha256=sha(blob),sample_hz=summary['sample_hz'],
            complete_transactions=len(rows),compared_transactions=commands,
            leading_partial=d['transactions'][0]['leading_partial'],
            trailing_partial=d['transactions'][-1]['trailing_partial'],
            unexamined_complete_tail=len(rows)-commands,
            interval_lower_bounds_ns=minima,missing_intervals=unknown))
    duplicate_inputs=len({sha(b) for b in blobs})!=len(blobs)
    if duplicate_inputs:
        reasons.append('identical raw files do not establish independent repeat captures')
    return dict(schema=1,rom_sha256=sha(rom),skip=decoded[0]['summary']['skip'],
        compared_transactions=commands,observations=observations,
        digital_envelope_pass=not reasons,rejection_reasons=sorted(set(reasons)),
        maximum_model_spi_hz=5000000,minimum_model_intervals_ns=LIMITS_NS,
        quantization_margin_samples=1,physical_timing_qualified=False,
        board_profile_ready=False,copy_check_identity_confirmed=False,
        full_boot_coverage=False,
        rows=[dict(command_hex=t['mosi_hex'][:8],clocks=t['clocks'],
                   original_data_hex=t.get('data_hex')) for t in complete[0][:commands]],
        remaining=['Confirm captures are independent boots armed before first bus traffic.',
                   'Identify the type50 RAM-copy and verification passes in context.',
                   'Cover the entire substitution window; one short capture is insufficient.',
                   'Measure real Pico feed/fault latency and shared-MISO handover.'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('captures',nargs='+',type=Path)
    p.add_argument('--rom',required=True,type=Path)
    p.add_argument('--commands',type=int,help='compare this many initial complete transactions; default common prefix length')
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    report=qualify([p.read_bytes() for p in args.captures],args.rom.read_bytes(),commands=args.commands)
    report['capture_paths']=[str(p) for p in args.captures]
    private_write(args.output,(json.dumps(report,indent=2)+'\n').encode())
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','observations')},indent=2))
    return 0 if report['digital_envelope_pass'] else 1


if __name__=='__main__':
    raise SystemExit(main())
