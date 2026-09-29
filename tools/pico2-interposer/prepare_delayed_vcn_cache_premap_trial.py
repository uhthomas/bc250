#!/usr/bin/env python3
"""Inspect PSP VCN cache words before the delayed firmware-map replay.

The result is an interposer view, deliberately not a standalone BIOS image.
No input image, EEPROM, or Pico QSPI flash is written.
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
import prepare_video_driver_trial as video


BASE_SHA = 'e8cfd3d91eeab51d7cf0bec1e5d213a59a4160d369c2f58a3433bd09336da581'
PROFILE_SHA = '262198ecf0c5bb85d81fec3446dbcce07ea54a3bf6cf17749d8fbb919fe4109c'
HOOK_SHA = '532ea804f2e46e32be2e5691e4a9ffd9f614080359de465dcc5374b2253116f7'
SAMPLES = {
    'cache-size0': ('f026becf5d4c484faae2db9e2455c8e6411e6ae088638f746005440f7d55063d',
                    80, 0x2010c, 'vcn-delayed-cache-size0-premap'),
    'cache-bar-low0': ('a95e2abe2af66b4c380ff2c1c0afef070698f021cc8ed788845da7ff1ec897b8',
                       80, 0x2107c, 'vcn-delayed-cache-bar-low0-premap'),
    'mpc-cntl': ('76d8f6e4426688927a1276598db18cd685914af1e04efda6f3e111304cefebd6',
                 80, 0x200dc, 'vcn-delayed-mpc-cntl-premap'),
    'map-windows': ('a3f11b54106c8f84c69a91ea1d6cf49159fbc1561a403c13aa2f2a66c1728958',
                    124, None, 'vcn-delayed-map-windows-premap'),
    'mpc-mux': ('a563c4df93e96779f5d839d69c74ddefc2a2a012aeddfd97f57f1ea42ad420ea',
                156, None, 'vcn-delayed-mpc-mux-premap'),
    'tmr-prefix': ('931be6cf5f368719e20dbc7843d30f0da3efeb1b8ac052c21b6c6ebf1bad8a56',
                   232, None, 'vcn-delayed-tmr-prefix-premap'),
    'tmr-map-control': ('1a415c2e032b164d350f9f0bc8af1a168ea2c353bac1a7c121d337741bf8b82c',
                        236, None, 'vcn-delayed-tmr-map-control'),
    'tmr-readattr-control': ('abf6ecdd5a471a81b987212e70ac7bac2a376d704a14c26338b3e6a234e5a1c4',
                             236, None, 'vcn-delayed-tmr-readattr-control'),
    'tmr-readattr-target': ('9080f6d7d4337c600a0effdde1a8a4b905347acba26278ff61ad003f75fe9f05',
                            232, None, 'vcn-delayed-tmr-readattr-target'),
}
HOOK = common.DRIVER + 0x17c8e
DISPATCH = common.DRIVER + 0x200
MAP_POINTER = common.DRIVER + 0x17cf0
MAP_ADDRESSES = common.DRIVER + 0x17d98
MAP_VALUES = common.DRIVER + 0x17fb8
TABLE_LEN = 17 * 4
EXPECTED_OLD_HOOK = bytes.fromhex('18 4c 18 4f')
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample', choices=tuple(SAMPLES), default='cache-size0')
    parser.add_argument('--direct-bo', action='store_true',
                        help='compare the guarded ordinary-BO map after the first VCPU wait')
    for name in ('base', 'base-profile', 'clean', 'signing-key', 'hook',
                 'dispatch', 'output-dir'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    if args.direct_bo and args.sample != 'map-windows':
        parser.error('--direct-bo requires --sample map-windows')
    base_sha = (bo_fetch.BO_TRIAL_SHA if args.direct_bo else BASE_SHA)
    profile_sha = (bo_fetch.BO_PROFILE_SHA if args.direct_bo else PROFILE_SHA)
    expected_map = (bo_fetch.EXPECTED_BO_MAP if args.direct_bo else video.EXPECTED_MAP)
    base = common.checked(args.base, base_sha)
    clean = common.checked(args.clean, common.CLEAN_SHA)
    profile_source = common.checked(args.base_profile, profile_sha).decode()
    hook = common.checked(args.hook, HOOK_SHA)
    dispatch_sha, dispatch_size, sample_address, profile_name = SAMPLES[args.sample]
    if args.direct_bo:
        profile_name += '-bo-fetch'
    dispatch = common.checked(args.dispatch, dispatch_sha)
    if len(base) != len(clean) or len(base) != 0x1000000:
        raise ValueError('unexpected ROM geometry')
    if len(hook) != 4 or len(dispatch) != dispatch_size:
        raise ValueError('unexpected Thumb patch geometry')
    common.verify_signed_parts(base)
    if base[HOOK:HOOK + 4] != EXPECTED_OLD_HOOK:
        raise ValueError('proven cache-map preloop instructions changed')
    old_table = struct.pack('<17I', *(address for address, _ in expected_map))
    old_values = struct.pack('<17I', *(value for _, value in expected_map))
    if (base[DISPATCH:DISPATCH + len(dispatch)] != bytes(len(dispatch)) or
            base[MAP_ADDRESSES:MAP_ADDRESSES + TABLE_LEN] != old_table or
            base[MAP_POINTER:MAP_POINTER + 4] !=
            (0xe17d98).to_bytes(4, 'little') or
            base[MAP_VALUES:MAP_VALUES + TABLE_LEN] != old_values):
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
            candidate[MAP_VALUES:MAP_VALUES + TABLE_LEN] != old_values or
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
        'purpose': f'read PSP VCN {args.sample} after first VCPU wait, before cache-map replay; RAM-only',
        'base_sha256': base_sha,
        'combined_sha256': sha(candidate),
        'profile_sha256': sha(profile),
        'changed_words': len(changed),
        'expected_patch_reads_per_pass': responses,
        'psp_dispatch_address': '0xe00200',
        'psp_sample_address': ('0xf400162ec0' if args.sample in ('tmr-map-control', 'tmr-readattr-control')
                               else '0xf41fa00000' if args.sample in ('tmr-prefix', 'tmr-readattr-target')
                               else hex(sample_address) if sample_address is not None
                               else [hex(address) for address in (
                                   (0x200e4, 0x200ec, 0x200f4)
                                   if args.sample == 'mpc-mux' else
                                   (0x2107c, 0x21078, 0x20108, 0x2010c,
                                    0x20eb0, 0x20eb4, 0x20110, 0x20114,
                                    0x20ec0, 0x20ec4, 0x20118, 0x2011c,
                                    0x2108c, 0x21088, 0x20150, 0x20154))]),
        'psp_sample_timing': 'before 17 cache-window replay writes',
        'full_width_comparison': args.sample in ('map-windows', 'mpc-mux',
                                                 'tmr-prefix', 'tmr-map-control',
                                                 'tmr-readattr-control', 'tmr-readattr-target'),
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
