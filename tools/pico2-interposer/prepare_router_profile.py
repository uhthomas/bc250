#!/usr/bin/env python3
"""Build an ISOLATED replay of every changed word from the retained signed pair.

The sequence is synthetic, not a recording of BC250 reads. It exercises the
real signer/TOS/driver bytes and copy-versus-check policy without a board flash.
It is never a board arming profile and contains no private signing key.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load_pair(path):
    m = json.loads(path.read_text())
    def verified(key, digest):
        source = Path(m[key])
        if not source.is_absolute():
            source = path.parent / source
        data = source.read_bytes()
        require(hashlib.sha256(data).hexdigest() == m[digest], f'{key} hash mismatch')
        return data
    clean, patched = verified('clean_path', 'clean_sha256'), verified('patched_path', 'patched_sha256')
    require(len(clean) == len(patched) == 0x1000000, 'expected two 16 MiB images')
    return m, clean, patched


def prepare(path,full_objects=False):
    m, clean, patched = load_pair(path)
    # Bench anchors, chosen only for exercising start-of-window logic. Real
    # anchors must come from a complete, repeated board capture.
    rows = [dict(command=0x03000000 | address,patch=False,word=0,
                 original=int.from_bytes(clean[address:address+4],'big'),
                 region='anchor',pass_number=0) for address in (0x100,0x104)]
    # Native model established first-copy patched, verification clean for t50.
    # The following sparse order is chosen for bench coverage, NOT inferred as
    # the physical PSP's transaction sequence. TOS/driver remain patched twice.
    for region, span, passes in (
        ('type50', m['type50_modulus_flash_range'], (True, False)),
        ('tos', m['tos_flash_range'], (True, True)),
        ('driver', m['driver_flash_range'], (True, True)),
    ):
        start, end = (int(x, 16) for x in span)
        if full_objects and region=='type50':
            start,end=0x9dad00,0x9dbad0
        require(start % 4 == end % 4 == 0, 'unaligned range')
        changed = [a for a in range(start, end, 4) if clean[a:a+4] != patched[a:a+4]]
        require(bool(changed), f'no changed words in {region}')
        for pass_number, replace in enumerate(passes):
            for address in (range(start,end,4) if full_objects else changed):
                substitute=replace and clean[address:address+4]!=patched[address:address+4]
                rows.append(dict(command=0x03000000 | address, patch=substitute,
                                 word=int.from_bytes(patched[address:address+4], 'big') if substitute else 0,
                                 original=int.from_bytes(clean[address:address+4], 'big'),
                                 region=region, pass_number=pass_number))
    touched = {r['command'] & 0xffffff for r in rows if r['patch']}
    all_changed = {a & ~3 for a, (x, y) in enumerate(zip(clean, patched)) if x != y}
    require(touched == all_changed, 'replay must cover every changed ROM word')
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    runs,payload=compress(rows)
    return dict(schema=3, name='isolated-signed-' + digest[:12], rows=rows, seek_anchor=True,
                row_sha256=digest, clean_sha256=m['clean_sha256'], patched_sha256=m['patched_sha256'],
                full_object_stress=full_objects,run_count=len(runs),payload_words=len(payload),
                compressed_bytes=len(runs)*12+max(1,len(payload))*4,expanded_bytes=len(rows)*12,
                unique_changed_words=len(touched), private_key_included=False,
                physical_trace=False, board_arm=False,
                warning='SYNTHETIC isolated replay; cannot be used as a BC250 boot profile')


def compress(rows):
    runs, payload = [], []
    for row in rows:
        command = row['command']
        require(command>>24==3 and command%4==0, 'aligned READ03 required')
        patch = row['patch']
        if (runs and command==runs[-1]['command']+4*runs[-1]['count'] and
                patch==(runs[-1]['payload']!=0xffffffff)):
            runs[-1]['count']+=1
        else:
            runs.append(dict(command=command,count=1,payload=len(payload) if patch else 0xffffffff))
        if patch:
            require(0<=row['word']<=0xffffffff,'reply word overflow')
            payload.append(row['word'])
    require(sum(r['count'] for r in runs)==len(rows), 'run length mismatch')
    return runs,payload


def header(plan):
    runs,payload=compress(plan['rows'])
    text = ['/* Generated synthetic replay. Public/signed words only. No private key. */',
            '#define ROUTER_PROFILE_NAME ' + json.dumps(plan['name']),
            f'#define ROUTER_PROFILE_ROWS {len(plan["rows"])}u',
            f'#define ROUTER_PROFILE_RUNS {len(runs)}u',
            f'#define ROUTER_PROFILE_PAYLOAD_WORDS {len(payload)}u',
            '/* Mutable placement copies metadata and replies to SRAM at boot. */',
            'static struct router_run router_runs[] = {']
    text += [f'    {{0x{r["command"]:08x}, {r["count"]}u, 0x{r["payload"]:08x}}},' for r in runs]
    text += ['};', 'static uint32_t router_payload[] = {']
    text += [f'    0x{word:08x},' for word in (payload or [0])]
    return '\n'.join(text + ['};', ''])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--full-objects',action='store_true',help='capacity stress: replay both complete copies of all three objects')
    args = p.parse_args()
    plan = prepare(args.manifest,args.full_objects)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, data in (('router_profile.h', header(plan)),
                       ('router_profile.json', json.dumps(plan, indent=2) + '\n')):
        fd = os.open(args.output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(data)
    print(json.dumps({k: v for k, v in plan.items() if k != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
