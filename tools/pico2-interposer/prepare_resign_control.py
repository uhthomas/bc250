#!/usr/bin/env python3
"""Build private, RAM-only controls for the type-50 signer and TOS hook.

The generated ROM is an interposer source only; never flash it to the BC250.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

KDB_MODULUS = 0x9db140
TOS, TOS_LEN = 0x8eac00, 0x14350
DRIVER, DRIVER_LEN = 0x984f00, 0x1a770
HOOK = TOS + 0x100 + 0x178
COMPONENT = TOS + 0x100 + 0x5c00
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', type=Path, required=True)
    parser.add_argument('--private-key', type=Path, required=True)
    parser.add_argument('--full-profile', type=Path, required=True)
    parser.add_argument('--full-patched', type=Path)
    parser.add_argument('--mode', choices=('resign-clean', 'bypass-hook', 'noop-hook', 'component-probe'), default='resign-clean')
    parser.add_argument('--component-binary', type=Path)
    parser.add_argument('--hook-offset', type=lambda value: int(value, 0), default=0x178)
    parser.add_argument('--name')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.hook_offset not in (0x140, 0x178):
        parser.error('--hook-offset must be 0x140 or 0x178')
    if args.hook_offset != 0x178 and args.mode != 'component-probe':
        parser.error('early hook offset requires --mode component-probe')

    clean = args.clean.read_bytes()
    if len(clean) != 0x1000000:
        raise ValueError('expected 16 MiB clean ROM')
    key = serialization.load_pem_private_key(args.private_key.read_bytes(), None)
    if key.key_size != 2048:
        raise ValueError('expected RSA-2048 signer')
    if args.mode != 'resign-clean':
        if args.full_patched is None:
            parser.error('hook controls require --full-patched')
        full = args.full_patched.read_bytes()
        if len(full) != len(clean) or full[HOOK:HOOK + 4] != bytes.fromhex('a01600ea'):
            raise ValueError('unexpected full TOS hook source')
        modified = bytearray(full)
        if args.mode == 'bypass-hook':
            modified[HOOK:HOOK + 4] = clean[HOOK:HOOK + 4]
        elif args.mode == 'noop-hook':
            # Run the hook, reproduce its displaced MOV, and resume at 0x17c.
            # Relative branch displacement is unchanged when TOS is copied to RAM.
            resume = HOOK + 4
            branch_at = COMPONENT + 4
            displacement = resume - (branch_at + 8)
            if displacement % 4 or not -(1 << 25) <= displacement < (1 << 25):
                raise ValueError('invalid ARM branch displacement')
            branch = (0xea000000 | ((displacement // 4) & 0xffffff)).to_bytes(4, 'little')
            modified[COMPONENT:COMPONENT + 8] = clean[HOOK:HOOK + 4] + branch
        else:
            if args.component_binary is None:
                parser.error('component-probe requires --component-binary')
            component = args.component_binary.read_bytes()
            if not 0 < len(component) <= 0x200 or len(component) % 4:
                raise ValueError('component probe must be 4-byte aligned and at most 512 bytes')
            modified[COMPONENT:COMPONENT + len(component)] = component
            if args.hook_offset == 0x140:
                modified[HOOK:HOOK + 4] = clean[HOOK:HOOK + 4]
                early_hook = TOS + 0x100 + 0x140
                displacement = COMPONENT - (early_hook + 8)
                if displacement % 4 or not -(1 << 25) <= displacement < (1 << 25):
                    raise ValueError('invalid early ARM branch displacement')
                modified[early_hook:early_hook + 4] = (
                    0xea000000 | ((displacement // 4) & 0xffffff)).to_bytes(4, 'little')
        payload = bytes(modified[TOS + 0x100:TOS + TOS_LEN - 256])
        modified[TOS + 0xd0:TOS + 0xf0] = hashlib.sha256(payload).digest()
    else:
        modified = bytearray(clean)
    modified[KDB_MODULUS:KDB_MODULUS + 256] = key.public_key().public_numbers().n.to_bytes(256, 'little')
    for address, length in ((TOS, TOS_LEN), (DRIVER, DRIVER_LEN)):
        body = bytes(modified[address:address + length - 256])
        signature = key.sign(body, PSS, hashes.SHA256())
        key.public_key().verify(signature, body, PSS, hashes.SHA256())
        modified[address + length - 256:address + length] = signature
    allowed = lambda i: (KDB_MODULUS <= i < KDB_MODULUS + 256 or
                         (args.mode != 'resign-clean' and
                          (TOS + 0xd0 <= i < TOS + 0xf0 or
                           (args.mode == 'component-probe' and args.hook_offset == 0x140 and
                            TOS + 0x100 + 0x140 <= i < TOS + 0x100 + 0x144) or
                           (args.mode in ('noop-hook', 'component-probe') and
                            args.hook_offset == 0x178 and HOOK <= i < HOOK + 4) or
                           TOS + 0x100 + 0x5c00 <= i < TOS + 0x100 + 0x5e00)) or
                         TOS + TOS_LEN - 256 <= i < TOS + TOS_LEN or
                         DRIVER + DRIVER_LEN - 256 <= i < DRIVER + DRIVER_LEN)
    if any(a != b and not allowed(i) for i, (a, b) in enumerate(zip(clean, modified))):
        raise ValueError('control changed a signed body or another ROM byte')

    source = args.full_profile.read_text()
    run_block = source.split('static const struct expected_run expected_runs[PROFILE_RUNS] = {', 1)[1].split('};', 1)[0]
    runs = [(int(a, 16), int(count)) for a, count in
            re.findall(r'\{0x([0-9a-f]+)u, (\d+)u\}', run_block)]
    if len(runs) != 37 or sum(count for _, count in runs) != 872744:
        raise ValueError('unexpected full boot profile')
    changed = [(0x03000000 | address, int.from_bytes(modified[address:address + 4], 'big'))
               for address in range(0, len(clean), 4)
               if clean[address:address + 4] != modified[address:address + 4]]
    replies = 0
    row = 0
    changes = {command for command, _ in changed}
    for start, count in runs:
        for offset in range(count):
            command = start + 4 * offset
            if command in changes and not (0x9dad00 <= (command & 0xffffff) < 0x9dbad0 and row >= 696):
                replies += 1
            row += 1
    if not changed or not replies:
        raise ValueError('empty physical control')
    name = args.name or args.mode
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', name):
        raise ValueError('invalid profile name')
    lines = ['/* Private re-sign-only interposer control; never flash to the BC250. */',
             '#ifndef BC250_SPARSE_PHYSICAL_PROFILE_H',
             '#define BC250_SPARSE_PHYSICAL_PROFILE_H',
             f'#define PROFILE_NAME "{name}"',
             '#define PROFILE_ROWS 872744u',
             '#define PROFILE_RUNS 37u',
             f'#define PROFILE_CHANGED_WORDS {len(changed)}u',
             '#define PROFILE_SECOND_KEYDB_ROW 696u',
             f'#define PROFILE_EXPECTED_PATCH_READS {replies}u',
             'static const struct expected_run expected_runs[PROFILE_RUNS] = {' + run_block + '};',
             'static const struct patch_word patch_words[PROFILE_CHANGED_WORDS] = {']
    lines += [f'    {{0x{command:08x}u, 0x{value:08x}u}},' for command, value in changed]
    lines += ['};', '#endif', '']
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_private(args.output_dir / 'control-NEVER-flash.rom', bytes(modified))
    write_private(args.output_dir / 'sparse_physical_profile.h', '\n'.join(lines).encode())
    summary = dict(clean_sha256=hashlib.sha256(clean).hexdigest(),
                   control_sha256=hashlib.sha256(modified).hexdigest(),
                   changed_words=len(changed), expected_patch_reads_per_pass=replies,
                   bodies_byte_identical_to_clean=(args.mode == 'resign-clean'),
                   original_hook_restored=(args.mode == 'bypass-hook'),
                   noop_hook_only=(args.mode == 'noop-hook'),
                   hook_offset=hex(args.hook_offset),
                   component_probe_sha256=(hashlib.sha256(args.component_binary.read_bytes()).hexdigest()
                                           if args.component_binary else None),
                   bios_flash_allowed=False)
    write_private(args.output_dir / 'summary.json', (json.dumps(summary, indent=2) + '\n').encode())
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
