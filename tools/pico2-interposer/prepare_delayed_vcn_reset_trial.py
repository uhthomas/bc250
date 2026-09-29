#!/usr/bin/env python3
"""Reproduce the failed data-table delayed-read profile offline only.

Moving the cache-address table to 0xe19010 stalled powered LOAD_IP_FW on the
BC250, even in a relocation-only control. Use the code-cave trial instead.
The result is an interposer view, never a standalone BIOS or live candidate.
No input image, EEPROM, or Pico QSPI flash is written.
"""

import argparse
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import prepare_early_and_late_gasket_trial as common


BASE_SHA = 'e8cfd3d91eeab51d7cf0bec1e5d213a59a4160d369c2f58a3433bd09336da581'
PROFILE_SHA = '262198ecf0c5bb85d81fec3446dbcce07ea54a3bf6cf17749d8fbb919fe4109c'
HOOK_SHA = 'e74a71cd1124adc5d97195fc0214bb95bb79ee905bfe0fc62469ce106534aa95'
DISPATCH_SHA = '997157bacd7efcad865d25c68bfc74b9c80c2b965f6893162fda3577e870f017'
HOOK = common.DRIVER + 0x17ca6
DISPATCH = common.DRIVER + 0x17d98
MAP_POINTER = common.DRIVER + 0x17cf0
MAP_ADDRESSES = common.DRIVER + 0x19010
TABLE_LEN = 17 * 4
EXPECTED_OLD_HOOK = bytes.fromhex('14 48 00 21')
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'base-profile', 'clean', 'signing-key', 'hook',
                 'dispatch', 'output-dir'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    base = common.checked(args.base, BASE_SHA)
    clean = common.checked(args.clean, common.CLEAN_SHA)
    profile_source = common.checked(args.base_profile, PROFILE_SHA).decode()
    hook = common.checked(args.hook, HOOK_SHA)
    dispatch = common.checked(args.dispatch, DISPATCH_SHA)
    if len(base) != len(clean) or len(base) != 0x1000000:
        raise ValueError('unexpected ROM geometry')
    if len(hook) != 4 or len(dispatch) != 72:
        raise ValueError('unexpected Thumb patch geometry')
    common.verify_signed_parts(base)
    if base[HOOK:HOOK + 4] != EXPECTED_OLD_HOOK:
        raise ValueError('proven cache-map hook changed')
    old_table = b''.join(address.to_bytes(4, 'little') for address in (
        0x2107c, 0x21078, 0x20108, 0x2010c, 0x20eb0, 0x20eb4,
        0x20110, 0x20114, 0x20ec0, 0x20ec4, 0x20118, 0x2011c,
        0x2108c, 0x21088, 0x20150, 0x20154, 0x1f928))
    if (base[DISPATCH:DISPATCH + TABLE_LEN] != old_table or
            base[DISPATCH + TABLE_LEN:DISPATCH + len(dispatch)] !=
            bytes(len(dispatch) - TABLE_LEN) or
            base[MAP_POINTER:MAP_POINTER + 4] !=
            (0xe17d98).to_bytes(4, 'little') or
            base[MAP_ADDRESSES:MAP_ADDRESSES + TABLE_LEN] != bytes(TABLE_LEN)):
        raise ValueError('original VCN map table or its relocation space changed')

    key = serialization.load_pem_private_key(args.signing_key.read_bytes(),
                                             password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError('expected private RSA key')
    modulus = int.from_bytes(base[common.KDB_MODULUS:
                                  common.KDB_MODULUS + 256], 'little')
    if key.public_key().public_numbers().n != modulus:
        raise ValueError('private key does not match the interposer key DB')

    candidate = bytearray(base)
    candidate[HOOK:HOOK + 4] = hook
    candidate[DISPATCH:DISPATCH + len(dispatch)] = dispatch
    candidate[MAP_ADDRESSES:MAP_ADDRESSES + TABLE_LEN] = old_table
    candidate[MAP_POINTER:MAP_POINTER + 4] = (0xe19010).to_bytes(4, 'little')
    start, length = common.DRIVER, common.DRIVER_LEN
    candidate[start + 0xd0:start + 0xf0] = hashlib.sha256(
        candidate[start + 0x100:start + length - 256]).digest()
    candidate[start + length - 256:start + length] = key.sign(
        bytes(candidate[start:start + length - 256]), PSS, hashes.SHA256())
    common.verify_signed_parts(candidate)
    allowed = ((HOOK, HOOK + 4),
               (DISPATCH, DISPATCH + len(dispatch)),
               (MAP_ADDRESSES, MAP_ADDRESSES + TABLE_LEN),
               (MAP_POINTER, MAP_POINTER + 4),
               (start + 0xd0, start + 0xf0),
               (start + length - 256, start + length))
    if any(not any(lo <= offset < hi for lo, hi in allowed)
           for offset, (before, after) in enumerate(zip(base, candidate))
           if before != after):
        raise ValueError('candidate changed outside the guarded PSP driver spans')
    if candidate[common.TOS:common.TOS + common.TOS_LEN] != base[
            common.TOS:common.TOS + common.TOS_LEN]:
        raise AssertionError('early Trusted OS policy changed')

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
        raise ValueError('physical replay geometry changed')
    lines = [
        '/* Private RAM-only interposer view; NEVER flash to BC250. */',
        '#ifndef BC250_SPARSE_PHYSICAL_PROFILE_H',
        '#define BC250_SPARSE_PHYSICAL_PROFILE_H',
        '#define PROFILE_NAME "vcn-delayed-reset-read"',
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
    common.write_private(args.output_dir / 'sparse_physical_profile.h',
                         profile)
    summary = {
        'purpose': 'read PSP VCN reset after first VCPU wait; RAM-only',
        'base_sha256': BASE_SHA,
        'combined_sha256': sha(candidate),
        'profile_sha256': sha(profile),
        'changed_words': len(changed),
        'expected_patch_reads_per_pass': responses,
        'live_trial_allowed': False,
        'live_result': 'first powered LOAD_IP_FW timed out before delayed read',
        'bios_flash_allowed': False,
        'pico_qspi_write_allowed': False,
        'hardware_decode_verified': False,
    }
    common.write_private(args.output_dir / 'summary.json',
                         (json.dumps(summary, indent=2) + '\n').encode())
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
