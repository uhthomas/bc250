#!/usr/bin/env python3
"""Sample a delayed PSP VCN word without relocating the proven VCN map.

The result is an interposer view, deliberately not a standalone BIOS image.
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
HOOK_SHA = '488d92ae17115e658b21803985ac42e5b8f43c7c63f9e270147b469e419167cc'
SAMPLES = {
    'reset': ('f96dec89836333e47378a5945f651bcad04f132533f045ac1d14fcb8624b1040',
              72, 0x20180, 'vcn-delayed-reset-code'),
    'cache-size0': ('7cb2cdcd17555701fc61d9fdc12807b00624b183acd31b8021abd2a9b71e3b15',
                    76, 0x2010c, 'vcn-delayed-cache-size0-code'),
}
HOOK = common.DRIVER + 0x17ca6
DISPATCH = common.DRIVER + 0x200
MAP_POINTER = common.DRIVER + 0x17cf0
MAP_ADDRESSES = common.DRIVER + 0x17d98
MAP_VALUES = common.DRIVER + 0x17fb8
TABLE_LEN = 17 * 4
EXPECTED_OLD_HOOK = bytes.fromhex('14 48 00 21')
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample', choices=tuple(SAMPLES), default='reset')
    for name in ('base', 'base-profile', 'clean', 'signing-key', 'hook',
                 'dispatch', 'output-dir'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    base = common.checked(args.base, BASE_SHA)
    clean = common.checked(args.clean, common.CLEAN_SHA)
    profile_source = common.checked(args.base_profile, PROFILE_SHA).decode()
    hook = common.checked(args.hook, HOOK_SHA)
    dispatch_sha, dispatch_size, sample_address, profile_name = SAMPLES[args.sample]
    dispatch = common.checked(args.dispatch, dispatch_sha)
    if len(base) != len(clean) or len(base) != 0x1000000:
        raise ValueError('unexpected ROM geometry')
    if len(hook) != 4 or len(dispatch) != dispatch_size:
        raise ValueError('unexpected Thumb patch geometry')
    common.verify_signed_parts(base)
    if base[HOOK:HOOK + 4] != EXPECTED_OLD_HOOK:
        raise ValueError('proven cache-map hook changed')
    old_table = b''.join(address.to_bytes(4, 'little') for address in (
        0x2107c, 0x21078, 0x20108, 0x2010c, 0x20eb0, 0x20eb4,
        0x20110, 0x20114, 0x20ec0, 0x20ec4, 0x20118, 0x2011c,
        0x2108c, 0x21088, 0x20150, 0x20154, 0x1f928))
    if (base[DISPATCH:DISPATCH + len(dispatch)] != bytes(len(dispatch)) or
            base[MAP_ADDRESSES:MAP_ADDRESSES + TABLE_LEN] != old_table or
            base[MAP_POINTER:MAP_POINTER + 4] !=
            (0xe17d98).to_bytes(4, 'little') or
            base[MAP_VALUES:MAP_VALUES + TABLE_LEN] == bytes(TABLE_LEN)):
        raise ValueError('original RX VCN map tables or code cave changed')

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
    start, length = common.DRIVER, common.DRIVER_LEN
    candidate[start + 0xd0:start + 0xf0] = hashlib.sha256(
        candidate[start + 0x100:start + length - 256]).digest()
    candidate[start + length - 256:start + length] = key.sign(
        bytes(candidate[start:start + length - 256]), PSS, hashes.SHA256())
    common.verify_signed_parts(candidate)
    allowed = ((HOOK, HOOK + 4),
               (DISPATCH, DISPATCH + len(dispatch)),
               (start + 0xd0, start + 0xf0),
               (start + length - 256, start + length))
    if any(not any(lo <= offset < hi for lo, hi in allowed)
           for offset, (before, after) in enumerate(zip(base, candidate))
           if before != after):
        raise ValueError('candidate changed outside the guarded PSP driver spans')
    if candidate[common.TOS:common.TOS + common.TOS_LEN] != base[
            common.TOS:common.TOS + common.TOS_LEN]:
        raise AssertionError('early Trusted OS policy changed')
    if (candidate[MAP_ADDRESSES:MAP_ADDRESSES + TABLE_LEN] != old_table or
            candidate[MAP_VALUES:MAP_VALUES + TABLE_LEN] !=
            base[MAP_VALUES:MAP_VALUES + TABLE_LEN] or
            candidate[MAP_POINTER:MAP_POINTER + 4] !=
            (0xe17d98).to_bytes(4, 'little')):
        raise AssertionError('proven RX code-region map moved')

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
        f'#define PROFILE_NAME "{profile_name}"',
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
        'purpose': f'read PSP VCN {args.sample} after first VCPU wait from RX code cave; RAM-only',
        'base_sha256': BASE_SHA,
        'combined_sha256': sha(candidate),
        'profile_sha256': sha(profile),
        'changed_words': len(changed),
        'expected_patch_reads_per_pass': responses,
        'psp_dispatch_address': '0xe00200',
        'psp_sample_address': hex(sample_address),
        'psp_sample_timing': 'after the 17 cache-window replay writes',
        'cache_map_persistence_claim_allowed': False,
        'vcn_map_tables_relocated': False,
        'bios_flash_allowed': False,
        'pico_qspi_write_allowed': False,
        'hardware_decode_verified': False,
    }
    common.write_private(args.output_dir / 'summary.json',
                         (json.dumps(summary, indent=2) + '\n').encode())
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
