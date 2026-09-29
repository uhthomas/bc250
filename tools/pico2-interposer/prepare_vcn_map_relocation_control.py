#!/usr/bin/env python3
"""Reproduce the failed PSP VCN cache-address relocation control offline.

No executable instruction changes. The original table is left in place so
this isolates the driver's pointer/data-memory route from the delayed hook.
The live control timed out on powered LOAD_IP_FW; do not run it again.
"""

import argparse
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import prepare_early_and_late_gasket_trial as common
import prepare_delayed_vcn_reset_trial as delayed


PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)
OLD_TABLE = common.DRIVER + 0x17d98
NEW_TABLE = common.DRIVER + 0x19010
POINTER = common.DRIVER + 0x17cf0
TABLE_SIZE = 17 * 4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'base-profile', 'clean', 'signing-key', 'output-dir'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    base = common.checked(args.base, delayed.BASE_SHA)
    clean = common.checked(args.clean, common.CLEAN_SHA)
    profile_source = common.checked(args.base_profile, delayed.PROFILE_SHA).decode()
    if len(base) != len(clean) or len(base) != 0x1000000:
        raise ValueError('unexpected ROM geometry')
    common.verify_signed_parts(base)
    old = base[OLD_TABLE:OLD_TABLE + TABLE_SIZE]
    if (old != b''.join(address.to_bytes(4, 'little') for address in (
            0x2107c, 0x21078, 0x20108, 0x2010c, 0x20eb0, 0x20eb4,
            0x20110, 0x20114, 0x20ec0, 0x20ec4, 0x20118, 0x2011c,
            0x2108c, 0x21088, 0x20150, 0x20154, 0x1f928)) or
            base[NEW_TABLE:NEW_TABLE + TABLE_SIZE] != bytes(TABLE_SIZE) or
            base[POINTER:POINTER + 4] != (0xe17d98).to_bytes(4, 'little')):
        raise ValueError('pinned map table or pointer changed')
    key = serialization.load_pem_private_key(args.signing_key.read_bytes(),
                                             password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError('expected private RSA key')
    modulus = int.from_bytes(base[common.KDB_MODULUS:
                                  common.KDB_MODULUS + 256], 'little')
    if key.public_key().public_numbers().n != modulus:
        raise ValueError('signer does not match pinned interposer key DB')

    candidate = bytearray(base)
    candidate[NEW_TABLE:NEW_TABLE + TABLE_SIZE] = old
    candidate[POINTER:POINTER + 4] = (0xe19010).to_bytes(4, 'little')
    start, length = common.DRIVER, common.DRIVER_LEN
    candidate[start + 0xd0:start + 0xf0] = hashlib.sha256(
        candidate[start + 0x100:start + length - 256]).digest()
    candidate[start + length - 256:start + length] = key.sign(
        bytes(candidate[start:start + length - 256]), PSS, hashes.SHA256())
    common.verify_signed_parts(candidate)
    allowed = ((NEW_TABLE, NEW_TABLE + TABLE_SIZE), (POINTER, POINTER + 4),
               (start + 0xd0, start + 0xf0),
               (start + length - 256, start + length))
    if any(not any(lo <= offset < hi for lo, hi in allowed)
           for offset, (before, after) in enumerate(zip(base, candidate))
           if before != after):
        raise ValueError('unexpected control-image change')

    block, runs = common.physical_runs(profile_source)
    changed = [(0x03000000 | offset,
                int.from_bytes(candidate[offset:offset + 4], 'big'))
               for offset in range(0, len(clean), 4)
               if candidate[offset:offset + 4] != clean[offset:offset + 4]]
    addresses = {address for address, _ in changed}
    responses = row = 0
    for first, count in runs:
        for index in range(count):
            command = first + 4 * index
            address = command & 0xffffff
            if (command in addresses and
                    not (0x9dad00 <= address < 0x9dbad0 and row >= 696) and
                    not (0x9dbda0 <= address < 0x9dbef0 and row >= 873080)):
                responses += 1
            row += 1
    if row != 873480 or responses < 927:
        raise ValueError('physical profile geometry changed')
    lines = [
        '/* Private RAM-only relocation control; NEVER flash to BC250. */',
        '#ifndef BC250_SPARSE_PHYSICAL_PROFILE_H',
        '#define BC250_SPARSE_PHYSICAL_PROFILE_H',
        '#define PROFILE_NAME "vcn-map-relocation-control"',
        '#define PROFILE_ROWS 873480u',
        '#define PROFILE_RUNS 39u',
        f'#define PROFILE_CHANGED_WORDS {len(changed)}u',
        '#define PROFILE_SECOND_KEYDB_ROW 696u',
        '#define PROFILE_TYPE51_HASH_ROW 873080u',
        f'#define PROFILE_EXPECTED_PATCH_READS {responses}u',
        'static const struct expected_run expected_runs[PROFILE_RUNS] = {' + block + '};',
        'static const struct patch_word patch_words[PROFILE_CHANGED_WORDS] = {',
        *(f'    {{0x{address:08x}u, 0x{value:08x}u}},'
          for address, value in changed),
        '};', '#endif', '',
    ]
    profile = '\n'.join(lines).encode()
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    common.write_private(args.output_dir / 'trial-NEVER-flash.rom',
                         bytes(candidate))
    common.write_private(args.output_dir / 'sparse_physical_profile.h', profile)
    summary = {
        'purpose': 'VCN cache-address table relocation only; RAM-only control',
        'base_sha256': delayed.BASE_SHA,
        'combined_sha256': hashlib.sha256(candidate).hexdigest(),
        'profile_sha256': hashlib.sha256(profile).hexdigest(),
        'changed_words': len(changed),
        'expected_patch_reads_per_pass': responses,
        'executable_instructions_changed': False,
        'live_trial_allowed': False,
        'live_result': 'first powered LOAD_IP_FW timed out',
        'bios_flash_allowed': False,
        'pico_qspi_write_allowed': False,
    }
    common.write_private(args.output_dir / 'summary.json',
                         (json.dumps(summary, indent=2) + '\n').encode())
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
