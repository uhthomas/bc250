#!/usr/bin/env python3
"""Change only the early PSP diagnostic read target to a pinned SMN control.

This is a RAM-only address-map experiment based on a previously booted early
VCN read profile. The PSP service maps the argument to its 0x01000000 window;
this trial tests whether that view aliases the host's root-SMN reading.
The generated ROM is invalid as a standalone BIOS image. Never flash it.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from prepare_policy_control_trial import parse_header, replies_for


CLEAN_SHA = 'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183'
BASE_SHA = '33fca2cab7f10c69dfdb9c3f174b9af833b68104750523f5a0a393cdb59c1771'
PROFILE_SHA = 'cd3cad961de7fde7f1b39ead8da438dd19eb9a64ffac42db5270e8971ea12f7e'
CAVE_SHA = '31b088e27f0a233e42cf3d80958b524f0bb10fa4779dc874dfe9cfc73ea9db1c'
DRIVER, DRIVER_LEN = 0x984f00, 0x1a770
TOS, TOS_LEN = 0x8eac00, 0x14350
CAVE = DRIVER + 0x17c54
LITERAL = CAVE + 0x34
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', required=True, type=Path)
    parser.add_argument('--base-rom', required=True, type=Path)
    parser.add_argument('--base-profile', required=True, type=Path)
    parser.add_argument('--base-cave', required=True, type=Path)
    parser.add_argument('--private-key', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--target', type=lambda raw: int(raw, 0),
                        choices=(0x50d6c, 0x5a870), default=0x50d6c,
                        help='pinned fabric or core-mask read-only control')
    args = parser.parse_args()

    clean, base = args.clean.read_bytes(), args.base_rom.read_bytes()
    source = args.base_profile.read_bytes()
    cave = args.base_cave.read_bytes()
    if (len(clean) != 0x1000000 or len(base) != len(clean) or
            sha(clean) != CLEAN_SHA or sha(base) != BASE_SHA or
            sha(source) != PROFILE_SHA or len(cave) != 60 or sha(cave) != CAVE_SHA):
        raise ValueError('clean ROM or pinned early-read trial differs')
    if (base[CAVE:CAVE+len(cave)] != cave or
            cave[0x34:0x38] != bytes.fromhex('1cf80100') or
            cave[0x38:0x3c] != bytes.fromhex('a4f80100') or
            clean[CAVE:CAVE+len(cave)] != bytes(len(cave))):
        raise ValueError('the previous read-only cave changed')
    profile = source.decode()
    runs, old_words = parse_header(profile)
    expected_old = [(0x03000000 | i, int.from_bytes(base[i:i+4], 'big'))
                    for i in range(0, len(base), 4)
                    if clean[i:i+4] != base[i:i+4]]
    if (len(old_words) != 319 or old_words != expected_old or
            replies_for(runs, old_words) != 385):
        raise ValueError('prior physical response set differs')

    key = serialization.load_pem_private_key(args.private_key.read_bytes(), None)
    if key.key_size != 2048:
        raise ValueError('expected RSA-2048 signer')
    if base[0x9db140:0x9db240] != key.public_key().public_numbers().n.to_bytes(256, 'little'):
        raise ValueError('prior type-30 signer differs')
    for address, length in ((TOS, TOS_LEN), (DRIVER, DRIVER_LEN)):
        body = base[address:address+length-256]
        key.public_key().verify(base[address+length-256:address+length], body,
                                PSS, hashes.SHA256())

    modified = bytearray(base)
    modified[LITERAL:LITERAL+4] = args.target.to_bytes(4, 'little')
    modified[DRIVER+0xd0:DRIVER+0xf0] = hashlib.sha256(
        modified[DRIVER+0x100:DRIVER+DRIVER_LEN-256]).digest()
    body = bytes(modified[DRIVER:DRIVER+DRIVER_LEN-256])
    signature = key.sign(body, PSS, hashes.SHA256())
    key.public_key().verify(signature, body, PSS, hashes.SHA256())
    modified[DRIVER+DRIVER_LEN-256:DRIVER+DRIVER_LEN] = signature
    allowed = ((LITERAL, LITERAL+4), (DRIVER+0xd0, DRIVER+0xf0),
               (DRIVER+DRIVER_LEN-256, DRIVER+DRIVER_LEN))
    if any(not any(lo <= i < hi for lo, hi in allowed)
           for i, (old, new) in enumerate(zip(base, modified)) if old != new):
        raise ValueError('change outside read argument or driver authentication')

    words = [(0x03000000 | i, int.from_bytes(modified[i:i+4], 'big'))
             for i in range(0, len(modified), 4)
             if clean[i:i+4] != modified[i:i+4]]
    replies = replies_for(runs, words)
    target_command = 0x03000000 | LITERAL
    target_hits = sum(start <= target_command < start + 4*count and
                      (target_command-start) % 4 == 0 for start, count in runs)
    if (replies < 380 or target_hits != 2 or
            dict(words).get(target_command) != int.from_bytes(
                modified[LITERAL:LITERAL+4], 'big') or words != sorted(words)):
        raise ValueError('new physical profile lacks target substitution')
    result = re.sub(r'#define PROFILE_NAME ".*"',
                    f'#define PROFILE_NAME "psp-{args.target:x}-read"', profile, count=1)
    result = re.sub(r'#define PROFILE_CHANGED_WORDS \d+u',
                    f'#define PROFILE_CHANGED_WORDS {len(words)}u', result, count=1)
    result = re.sub(r'#define PROFILE_EXPECTED_PATCH_READS \d+u',
                    f'#define PROFILE_EXPECTED_PATCH_READS {replies}u', result, count=1)
    lines = '\n'.join(f'    {{0x{a:08x}u, 0x{v:08x}u}},' for a, v in words)
    result = re.sub(r'(static const struct patch_word patch_words\[PROFILE_CHANGED_WORDS\] = \{).*?(\};)',
                    lambda m: m.group(1) + '\n' + lines + '\n' + m.group(2),
                    result, count=1, flags=re.DOTALL)
    if parse_header(result)[1] != words:
        raise ValueError('generated profile does not round-trip')

    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    private_write(args.output_dir/'trial-NEVER-flash.rom', bytes(modified))
    private_write(args.output_dir/'sparse_physical_profile.h', result.encode())
    summary = dict(mode=f'early-psp-{args.target:x}-read', clean_sha256=CLEAN_SHA,
                   base_sha256=BASE_SHA, trial_sha256=sha(modified),
                   profile_sha256=sha(result.encode()),
                   changed_words=len(words), expected_patch_reads_per_pass=replies,
                   psp_service_argument=f'{args.target:#x}',
                   psp_aperture_address=f'{0x01000000 + args.target:#x}',
                   target_writes=False, bios_flash_allowed=False)
    private_write(args.output_dir/'summary.json', (json.dumps(summary, indent=2)+'\n').encode())
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
