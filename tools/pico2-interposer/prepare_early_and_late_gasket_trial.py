#!/usr/bin/env python3
"""Combine two pinned RAM-only VCN probes without producing a flashable BIOS.

The early source contributes only its signed Trusted OS. The late source
contributes its signed PSP driver, authentic usage-6 key and TMR setup. Both
sources use the same temporary researcher signing key. The output is an SPI
interposer view and must NEVER be written to the BC250 BIOS EEPROM.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


CLEAN_SHA = 'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183'
EARLY_VARIANTS = {
    'cezanne': ('f6535d79809e4cc97595113bd4fd2eb9992afbb6111bc12d060e4b2062abb732', 464),
    'deck-hybrid': ('17f1c3e8662a69a2f0bd3598dcbe6b9226c2aef7a303e97eb9ae7b5e5a7dd185', 480),
}
LATE_VARIANTS = {
    'policy': (
        'e353cc979369b122b16db0109e71656be918e92189ecef654bea67d95172f7db',
        '0059be5e54f1996cbf7457f197852c8361d4669ad6664f1b5ba84876cac69cbf',
    ),
    'postcache-reset-release': (
        'cb50e8a1ac14e56983aa57b5d67c5a327f344904905663c182f48ef2baf5b178',
        'a29aadd08bede24516bf0c4cb9bdb656b6152a8b2124eb0bce1dcfd2d2c47c13',
    ),
}
TOS, TOS_LEN = 0x8eac00, 0x14350
DRIVER, DRIVER_LEN = 0x984f00, 0x1a770
KDB_MODULUS = 0x9db140
TOS_ENTRY = TOS + 0x100
TOS_CAVE = TOS_ENTRY + 0x5c00
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)


def checked(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f'input hash differs: {path}')
    return data


def write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)


def verify_signed_parts(rom: bytes) -> None:
    modulus = int.from_bytes(rom[KDB_MODULUS:KDB_MODULUS + 256], 'little')
    public = rsa.RSAPublicNumbers(65537, modulus).public_key()
    for start, length in ((TOS, TOS_LEN), (DRIVER, DRIVER_LEN)):
        body = rom[start:start + length - 256]
        public.verify(rom[start + length - 256:start + length], body, PSS,
                      hashes.SHA256())
        assert rom[start + 0xd0:start + 0xf0] == hashlib.sha256(
            rom[start + 0x100:start + length - 256]).digest()


def physical_runs(source: str) -> tuple[str, list[tuple[int, int]]]:
    key = 'static const struct expected_run expected_runs[PROFILE_RUNS] = {'
    block = source.split(key, 1)[1].split('};', 1)[0]
    runs = [(int(address, 16), int(count)) for address, count in
            re.findall(r'\{0x([0-9a-f]+)u, (\d+)u\}', block)]
    if len(runs) != 39 or sum(count for _, count in runs) != 873480:
        raise ValueError('late physical trace geometry changed')
    return block, runs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', type=Path, required=True)
    parser.add_argument('--early', type=Path, required=True)
    parser.add_argument('--early-variant', choices=tuple(EARLY_VARIANTS),
                        default='cezanne')
    parser.add_argument('--late', type=Path, required=True)
    parser.add_argument('--late-profile', type=Path, required=True)
    parser.add_argument('--late-variant', choices=tuple(LATE_VARIANTS),
                        default='policy')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    clean = checked(args.clean, CLEAN_SHA)
    early_sha, early_cave_length = EARLY_VARIANTS[args.early_variant]
    early = checked(args.early, early_sha)
    late_sha, profile_sha = LATE_VARIANTS[args.late_variant]
    late = checked(args.late, late_sha)
    profile_source = checked(args.late_profile, profile_sha).decode()
    if not all(len(image) == 0x1000000 for image in (clean, early, late)):
        raise ValueError('expected three 16-MiB images')
    verify_signed_parts(early)
    verify_signed_parts(late)
    if early[KDB_MODULUS:KDB_MODULUS + 256] != late[KDB_MODULUS:KDB_MODULUS + 256]:
        raise ValueError('the two temporary signing keys differ')
    if early[TOS_ENTRY:TOS_ENTRY + 4] != bytes.fromhex('fe1600ea'):
        raise ValueError('early entry branch differs')
    if early[TOS_CAVE:TOS_CAVE + early_cave_length] == clean[
            TOS_CAVE:TOS_CAVE + early_cave_length]:
        raise ValueError('early gasket hook missing')
    early_allowed = ((TOS + 0xd0, TOS + 0xf0),
                     (TOS_ENTRY, TOS_ENTRY + 4),
                     (TOS_CAVE, TOS_CAVE + early_cave_length),
                     (TOS + TOS_LEN - 256, TOS + TOS_LEN))
    if any(not any(lo <= i < hi for lo, hi in early_allowed)
           for i in range(TOS, TOS + TOS_LEN) if early[i] != clean[i]):
        raise ValueError('early Trusted OS has unexpected changes')

    combined = bytearray(late)
    combined[TOS:TOS + TOS_LEN] = early[TOS:TOS + TOS_LEN]
    verify_signed_parts(combined)
    if combined[DRIVER:DRIVER + DRIVER_LEN] != late[DRIVER:DRIVER + DRIVER_LEN]:
        raise AssertionError('late PSP driver changed')
    if combined[:TOS] != late[:TOS] or combined[TOS + TOS_LEN:] != late[TOS + TOS_LEN:]:
        raise AssertionError('change escaped the Trusted OS region')

    block, runs = physical_runs(profile_source)
    changed = [(0x03000000 | i, int.from_bytes(combined[i:i + 4], 'big'))
               for i in range(0, len(clean), 4)
               if combined[i:i + 4] != clean[i:i + 4]]
    changes = {address for address, _ in changed}
    responses, row = 0, 0
    for start, count in runs:
        for offset in range(count):
            command = start + 4 * offset
            address = command & 0xffffff
            if (command in changes and
                    not (0x9dad00 <= address < 0x9dbad0 and row >= 696) and
                    not (0x9dbda0 <= address < 0x9dbef0 and row >= 873080)):
                responses += 1
            row += 1
    if row != 873480 or responses < 557:
        raise ValueError('physical reply count is implausible')
    name = ('vcn-early-and-late-gasket' if args.late_variant == 'policy'
            else 'vcn-early-postcache-reset-release')
    if args.early_variant == 'deck-hybrid':
        name += '-deck-hybrid'
    lines = [
        '/* Private RAM-only interposer view; NEVER flash to BC250. */',
        '#ifndef BC250_SPARSE_PHYSICAL_PROFILE_H',
        '#define BC250_SPARSE_PHYSICAL_PROFILE_H',
        f'#define PROFILE_NAME "{name}"',
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
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_private(args.output_dir / 'trial-NEVER-flash.rom', bytes(combined))
    write_private(args.output_dir / 'sparse_physical_profile.h',
                  '\n'.join(lines).encode())
    summary = {
        'purpose': ('early plus late client-12 policy and successful PSP-side '
                    'VCN cache/reset release, signed VCN load; RAM-only'
                    if args.late_variant == 'postcache-reset-release' else
                    'early plus late client-12 policy, signed VCN load; RAM-only'),
        'late_variant': args.late_variant,
        'early_variant': args.early_variant,
        'clean_sha256': CLEAN_SHA,
        'early_sha256': early_sha,
        'late_sha256': late_sha,
        'combined_sha256': hashlib.sha256(combined).hexdigest(),
        'profile_sha256': hashlib.sha256('\n'.join(lines).encode()).hexdigest(),
        'changed_words': len(changed),
        'expected_patch_reads_per_pass': responses,
        'bios_flash_allowed': False,
        'pico_qspi_write_allowed': False,
        'hardware_decode_verified': False,
    }
    write_private(args.output_dir / 'summary.json',
                  (json.dumps(summary, indent=2) + '\n').encode())
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
