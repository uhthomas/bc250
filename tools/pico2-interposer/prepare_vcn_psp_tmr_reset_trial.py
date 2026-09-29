#!/usr/bin/env python3
"""Keep the verified reset oracle, but map VCPU firmware cache 0 to TMR.

Only the firmware BAR low word and offset change. The other fifteen PSP
map values, diagnostic hook, policy and signed components stay pinned.
The output is a RAM-interposer view; never flash it to the BC250 EEPROM.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import prepare_early_and_late_gasket_trial as common
import prepare_vcn_psp_bo_fetch_trial as bo_fetch


BASE_SHA = 'd7ef6d53efce665baca80c635daa6a4bcfe2dbf116cb2a3fece90c629f3be0aa'
PROFILE_SHA = 'ae73598c8a3d4b6f4bd56fa4c8663bfd81100888caf8abd2e304798318b55117'
MAP_VALUES = common.DRIVER + 0x17fb8
MAP_ADDRESSES = common.DRIVER + 0x17d98
COUNT = 17
TMR_MAP = (
    (0x2107c, 0x1fa00000), (0x21078, 0xf4),
    (0x20108, 0), (0x2010c, 0x64000),
    *bo_fetch.EXPECTED_BO_MAP[4:],
)
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'base-profile', 'clean', 'signing-key', 'output-dir'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    base = common.checked(args.base, BASE_SHA)
    source = common.checked(args.base_profile, PROFILE_SHA).decode()
    clean = common.checked(args.clean, common.CLEAN_SHA)
    if len(base) != len(clean) or len(base) != 0x1000000:
        raise ValueError('unexpected ROM geometry')
    common.verify_signed_parts(base)
    old_addrs = struct.unpack_from('<17I', base, MAP_ADDRESSES)
    old_vals = struct.unpack_from('<17I', base, MAP_VALUES)
    if tuple(zip(old_addrs, old_vals)) != bo_fetch.EXPECTED_BO_MAP:
        raise ValueError('pinned ordinary-BO map changed')
    if tuple(a for a, _ in TMR_MAP) != old_addrs or \
            TMR_MAP[4:] != bo_fetch.EXPECTED_BO_MAP[4:]:
        raise ValueError('TMR trial changed another cache window')

    key = serialization.load_pem_private_key(args.signing_key.read_bytes(),
                                             password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError('expected private RSA key')
    modulus = int.from_bytes(base[common.KDB_MODULUS:
                                  common.KDB_MODULUS + 256], 'little')
    if key.public_key().public_numbers().n != modulus:
        raise ValueError('private key differs from interposer key DB')

    candidate = bytearray(base)
    candidate[MAP_VALUES:MAP_VALUES + COUNT * 4] = struct.pack(
        '<17I', *(v for _, v in TMR_MAP))
    start, length = common.DRIVER, common.DRIVER_LEN
    candidate[start + 0xd0:start + 0xf0] = hashlib.sha256(
        candidate[start + 0x100:start + length - 256]).digest()
    candidate[start + length - 256:start + length] = key.sign(
        bytes(candidate[start:start + length - 256]), PSS, hashes.SHA256())
    common.verify_signed_parts(candidate)
    allowed = ((MAP_VALUES, MAP_VALUES + COUNT * 4),
               (start + 0xd0, start + 0xf0),
               (start + length - 256, start + length))
    if any(not any(lo <= offset < hi for lo, hi in allowed)
           for offset, (before, after) in enumerate(zip(base, candidate))
           if before != after):
        raise ValueError('candidate changed outside map/hash/signature')
    if candidate[common.TOS:common.TOS + common.TOS_LEN] != base[
            common.TOS:common.TOS + common.TOS_LEN]:
        raise ValueError('early Trusted OS policy changed')

    block, runs = common.physical_runs(source)
    changed = [(0x03000000 | offset,
                int.from_bytes(candidate[offset:offset + 4], 'big'))
               for offset in range(0, len(clean), 4)
               if candidate[offset:offset + 4] != clean[offset:offset + 4]]
    addresses = {address for address, _ in changed}
    responses = row = 0
    for first, count in runs:
        for index in range(count):
            command = first + 4 * index
            offset = command & 0xffffff
            if (command in addresses and
                    not (0x9dad00 <= offset < 0x9dbad0 and row >= 696) and
                    not (0x9dbda0 <= offset < 0x9dbef0 and row >= 873080)):
                responses += 1
            row += 1
    if row != 873480 or responses < 927:
        raise ValueError('physical replay geometry differs')
    lines = [
        '/* Private RAM-only interposer view; NEVER flash to BC250. */',
        '#ifndef BC250_SPARSE_PHYSICAL_PROFILE_H',
        '#define BC250_SPARSE_PHYSICAL_PROFILE_H',
        '#define PROFILE_NAME "vcn-delayed-map-reset-premap-tmr-fetch"',
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
        'purpose': 'PSP VCPU firmware cache TMR source with BO stack and reset oracle; RAM-only',
        'base_sha256': BASE_SHA,
        'combined_sha256': sha(candidate),
        'profile_sha256': sha(profile),
        'map_values': [[hex(a), hex(v)] for a, v in TMR_MAP],
        'changed_words': len(changed),
        'expected_patch_reads_per_pass': responses,
        'bios_flash_allowed': False,
        'pico_qspi_write_allowed': False,
        'hardware_decode_verified': False,
    }
    common.write_private(args.output_dir / 'summary.json',
                         (json.dumps(summary, indent=2) + '\n').encode())
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
