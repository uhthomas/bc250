#!/usr/bin/env python3
"""Move guarded PSP VCN cache windows to a pinned ordinary firmware BO.

Produces only a RAM-interposer view. Never write its ROM to either flash chip.
The matching opt-in kernel module verifies the live BO address and payload.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import prepare_early_and_late_gasket_trial as common
import prepare_video_driver_trial as video


BASE_SHA = 'e8cfd3d91eeab51d7cf0bec1e5d213a59a4160d369c2f58a3433bd09336da581'
PROFILE_SHA = '262198ecf0c5bb85d81fec3446dbcce07ea54a3bf6cf17749d8fbb919fe4109c'
BO_TRIAL_SHA = 'c1064547359793e27904a7c97800fe5f2636007cc9ed419193eeef913e7fa51a'
BO_PROFILE_SHA = '386158ba575f0ed3077476da7b330cd15397c75bfe2a5c708b8283fea736a09f'
MAP_VALUES = common.DRIVER + 0x17fb8
MAP_ADDRESSES = common.DRIVER + 0x17d98
COUNT = 17
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)
EXPECTED_BO_MAP = (
    (0x2107c, 0x1fc00000), (0x21078, 0xf4),
    (0x20108, 0x20), (0x2010c, 0x64000),
    (0x20eb0, 0x1fc64000), (0x20eb4, 0xf4),
    (0x20110, 0), (0x20114, 0x20000),
    (0x20ec0, 0x1fc84000), (0x20ec4, 0xf4),
    (0x20118, 0), (0x2011c, 0x80000),
    (0x2108c, 0x1fd04000), (0x21088, 0xf4),
    (0x20150, 0), (0x20154, 0x1000),
    (0x1f928, 0x100044),
)


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
    if tuple(zip(old_addrs, old_vals)) != video.EXPECTED_MAP:
        raise ValueError('pinned PSP VCN map differs')
    if tuple(addr for addr, _ in EXPECTED_BO_MAP) != old_addrs:
        raise ValueError('new mapping changed address order')
    if EXPECTED_BO_MAP[0][1] != 0x1fc00000 or EXPECTED_BO_MAP[2][1] != 0x20:
        raise ValueError('firmware BO base or 256-byte offset changed')
    if EXPECTED_BO_MAP[4][1] != EXPECTED_BO_MAP[0][1] + 0x64000:
        raise ValueError('stack BO offset differs')
    if EXPECTED_BO_MAP[8][1] != EXPECTED_BO_MAP[4][1] + 0x20000:
        raise ValueError('context BO offset differs')
    if EXPECTED_BO_MAP[12][1] != EXPECTED_BO_MAP[8][1] + 0x80000:
        raise ValueError('shared BO offset differs')

    key = serialization.load_pem_private_key(args.signing_key.read_bytes(),
                                             password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError('expected RSA private key')
    modulus = int.from_bytes(base[common.KDB_MODULUS:
                                  common.KDB_MODULUS + 256], 'little')
    if key.public_key().public_numbers().n != modulus:
        raise ValueError('key does not match interposer key database')

    candidate = bytearray(base)
    candidate[MAP_VALUES:MAP_VALUES + COUNT * 4] = struct.pack(
        '<17I', *(value for _, value in EXPECTED_BO_MAP))
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
        raise ValueError('candidate changed outside pinned PSP table/signature')
    if candidate[common.TOS:common.TOS + common.TOS_LEN] != base[
            common.TOS:common.TOS + common.TOS_LEN]:
        raise ValueError('early policy changed')
    if struct.unpack_from('<17I', candidate, MAP_ADDRESSES) != old_addrs or \
            struct.unpack_from('<17I', candidate, MAP_VALUES) != tuple(
                value for _, value in EXPECTED_BO_MAP):
        raise ValueError('map table verification failed')

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
        '#define PROFILE_NAME "vcn-psp-bo-fetch"',
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
        'purpose': 'signed PSP VCN cache map to pinned ordinary BO, RAM-only',
        'base_sha256': BASE_SHA,
        'combined_sha256': sha(candidate),
        'profile_sha256': sha(profile),
        'map_values': [[hex(a), hex(v)] for a, v in EXPECTED_BO_MAP],
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
