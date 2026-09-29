#!/usr/bin/env python3
"""Build the guarded, RAM-only PSP fabric bit-11 write/read/restore trial.

The input is the previously booted early PSP 0x50d6c read profile. Only its
read-only code cave, driver body hash and RSA-PSS signature may change. The
generated ROM view must never be written to the BC250 BIOS EEPROM.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from prepare_policy_control_trial import parse_header, private_write, replies_for


CLEAN_SHA = 'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183'
BASE_SHA = '5843fa0c4344a2e30a828a3b2ef04f882fd5f3d82e3b68d28d204ed9d3da55af'
PROFILE_SHA = '3cb33a102bc55e30cdd1ed455e21b45df07a80cc0d2597c151b1dfb98889d232'
CAVE_SHA = '042fe4b5b5d5ba03a4fbeaf22f575804ace0ae5d082ffada8df1c9c8750ead7b'
DRIVER, DRIVER_LEN = 0x984f00, 0x1a770
TOS, TOS_LEN = 0x8eac00, 0x14350
CAVE = DRIVER + 0x17c54
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', required=True, type=Path)
    parser.add_argument('--base-rom', required=True, type=Path)
    parser.add_argument('--base-profile', required=True, type=Path)
    parser.add_argument('--probe-cave', required=True, type=Path)
    parser.add_argument('--private-key', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()

    clean, base = args.clean.read_bytes(), args.base_rom.read_bytes()
    source = args.base_profile.read_bytes()
    cave = args.probe_cave.read_bytes()
    if (len(clean) != 0x1000000 or len(base) != len(clean) or
            sha(clean) != CLEAN_SHA or sha(base) != BASE_SHA or
            sha(source) != PROFILE_SHA or len(cave) != 124 or sha(cave) != CAVE_SHA):
        raise ValueError('pinned clean ROM, early read profile or probe cave differs')
    if (base[CAVE:CAVE+60][-8:] != bytes.fromhex('6c0d0500a4f80100') or
            any(base[CAVE+60:CAVE+len(cave)]) or
            clean[CAVE:CAVE+len(cave)] != bytes(len(cave))):
        raise ValueError('the previous code cave is not the expected read probe')
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
    modified[CAVE:CAVE+len(cave)] = cave
    modified[DRIVER+0xd0:DRIVER+0xf0] = hashlib.sha256(
        modified[DRIVER+0x100:DRIVER+DRIVER_LEN-256]).digest()
    body = bytes(modified[DRIVER:DRIVER+DRIVER_LEN-256])
    signature = key.sign(body, PSS, hashes.SHA256())
    key.public_key().verify(signature, body, PSS, hashes.SHA256())
    modified[DRIVER+DRIVER_LEN-256:DRIVER+DRIVER_LEN] = signature
    allowed = ((CAVE, CAVE+len(cave)), (DRIVER+0xd0, DRIVER+0xf0),
               (DRIVER+DRIVER_LEN-256, DRIVER+DRIVER_LEN))
    if any(not any(lo <= i < hi for lo, hi in allowed)
           for i, (old, new) in enumerate(zip(base, modified)) if old != new):
        raise ValueError('change outside guarded cave or driver authentication')
    words = [(0x03000000 | i, int.from_bytes(modified[i:i+4], 'big'))
             for i in range(0, len(modified), 4)
             if clean[i:i+4] != modified[i:i+4]]
    replies = replies_for(runs, words)
    if replies < 385 or words != sorted(words):
        raise ValueError('guarded profile lost physical substitutions')
    result = re.sub(r'#define PROFILE_NAME ".*"',
                    '#define PROFILE_NAME "psp-fabric-bit-probe"', profile, count=1)
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
    summary = dict(mode='guarded-psp-fabric-bit11-write-restore',
                   clean_sha256=CLEAN_SHA, base_sha256=BASE_SHA,
                   trial_sha256=sha(modified), profile_sha256=sha(result.encode()),
                   changed_words=len(words), expected_patch_reads_per_pass=replies,
                   guard_value='0xf0', trial_value='0x8f0', restore_value='0xf0',
                   bios_flash_allowed=False, pico_flash_allowed=False)
    private_write(args.output_dir/'summary.json', (json.dumps(summary, indent=2)+'\n').encode())
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
