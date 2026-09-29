#!/usr/bin/env python3
"""Build signed, RAM-only PSP/host VCN register-route comparisons.

The post-map hook reports the selected register after its own cache-window
writes. The pre-map hook reports it before any PSP window writes. Both check
a live PSP VCN power register. Copy the pinned early Trusted OS client-12
policy into either result. Never flash these views.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import prepare_early_and_late_gasket_trial as common


TARGETS = {
    'cache-low': (0x2107c, '0xffffffff'),
    'jpeg-dec-scratch0': (0x1e224, '0x5a13c0de'),
    'vcn-scratch1': (0x1f854, '0x5a13c0de'),
}
PHASES = {
    'post-map': {
        'late_sha': '6e9befc9ef177e2547f5e86230bb99da4507e4f1383abd0814704809af6d659d',
        'profile_sha': 'e0abfb9bf039031899a2c5405d8321a3881a370bf3d0849df00c5e19cbeca6f7',
        'report_literal': 0x99cbfc,
        'old_target': 0x1ffac,
        'name': 'vcn-early-postcache-cache-route',
    },
    'pre-psp-map': {
        'late_sha': 'f651cbc9a02a7e621ce36bdb3c685390c3860a59cbd8705f3325e8d5263cd984',
        'profile_sha': 'bc388ce6c4cd173abb09da36bbb89a47a444ca8a598b68926728db25d64ff453',
        'report_literal': 0x99cba4,
        'old_target': 0x20180,
        'name': 'vcn-early-prepspmap-cache-route',
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('clean', 'early', 'late', 'late-profile', 'signing-key', 'output-dir'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--phase', choices=tuple(PHASES), default='post-map')
    parser.add_argument('--target', choices=tuple(TARGETS), default='cache-low')
    args = parser.parse_args()
    phase = PHASES[args.phase]
    target, expected_host_read = TARGETS[args.target]

    clean = common.checked(args.clean, common.CLEAN_SHA)
    early = common.checked(args.early, common.EARLY_SHA)
    late = common.checked(args.late, phase['late_sha'])
    profile_source = common.checked(args.late_profile, phase['profile_sha']).decode()
    if not all(len(image) == 0x1000000 for image in (clean, early, late)):
        raise ValueError('expected 16-MiB ROM images')
    common.verify_signed_parts(early)
    common.verify_signed_parts(late)
    if late[common.KDB_MODULUS:common.KDB_MODULUS + 256] != early[
            common.KDB_MODULUS:common.KDB_MODULUS + 256]:
        raise ValueError('early and late signing keys differ')
    report_literal = phase['report_literal']
    if struct.unpack_from('<I', late, report_literal)[0] != phase['old_target']:
        raise ValueError('late report target has changed')

    key = serialization.load_pem_private_key(args.signing_key.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError('expected RSA signing key')
    modulus = int.from_bytes(late[common.KDB_MODULUS:common.KDB_MODULUS + 256],
                             'little')
    if key.public_key().public_numbers().n != modulus:
        raise ValueError('signing key differs from pinned key database')

    candidate = bytearray(late)
    struct.pack_into('<I', candidate, report_literal, target)
    start, length = common.DRIVER, common.DRIVER_LEN
    candidate[start + 0xd0:start + 0xf0] = hashlib.sha256(
        candidate[start + 0x100:start + length - 256]).digest()
    candidate[start + length - 256:start + length] = key.sign(
        bytes(candidate[start:start + length - 256]), common.PSS, hashes.SHA256())
    common.verify_signed_parts(candidate)
    allowed = ((report_literal, report_literal + 4),
               (start + 0xd0, start + 0xf0),
               (start + length - 256, start + length))
    if any(not any(lo <= i < hi for lo, hi in allowed)
           for i, (a, b) in enumerate(zip(late, candidate)) if a != b):
        raise ValueError('late ROM changed outside target/digest/signature')

    candidate[common.TOS:common.TOS + common.TOS_LEN] = early[
        common.TOS:common.TOS + common.TOS_LEN]
    common.verify_signed_parts(candidate)
    block, runs = common.physical_runs(profile_source)
    changed = [(0x03000000 | i, int.from_bytes(candidate[i:i + 4], 'big'))
               for i in range(0, len(clean), 4)
               if candidate[i:i + 4] != clean[i:i + 4]]
    changes = {address for address, _ in changed}
    responses, row = 0, 0
    for first, count in runs:
        for offset in range(count):
            command = first + 4 * offset
            address = command & 0xffffff
            if (command in changes and
                    not (0x9dad00 <= address < 0x9dbad0 and row >= 696) and
                    not (0x9dbda0 <= address < 0x9dbef0 and row >= 873080)):
                responses += 1
            row += 1
    if row != 873480 or responses < 557:
        raise ValueError('physical response geometry changed')
    lines = [
        '/* Private RAM-only interposer view; NEVER flash to BC250. */',
        '#ifndef BC250_SPARSE_PHYSICAL_PROFILE_H',
        '#define BC250_SPARSE_PHYSICAL_PROFILE_H',
        f'#define PROFILE_NAME "{phase["name"]}-{args.target}"',
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
    common.write_private(args.output_dir / 'trial-NEVER-flash.rom', bytes(candidate))
    common.write_private(args.output_dir / 'sparse_physical_profile.h', profile)
    summary = {
        'purpose': f'PSP {args.target} read at {args.phase} after early policy; RAM-only',
        'phase': args.phase,
        'target': args.target,
        'clean_sha256': common.CLEAN_SHA,
        'early_sha256': common.EARLY_SHA,
        'late_sha256': phase['late_sha'],
        'combined_sha256': hashlib.sha256(candidate).hexdigest(),
        'profile_sha256': hashlib.sha256(profile).hexdigest(),
        'changed_words': len(changed),
        'expected_patch_reads_per_pass': responses,
        'psp_report_address': hex(target),
        'expected_host_read': expected_host_read,
        'bios_flash_allowed': False,
        'pico_qspi_write_allowed': False,
        'hardware_decode_verified': False,
    }
    common.write_private(args.output_dir / 'summary.json',
                         (json.dumps(summary, indent=2) + '\n').encode())
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
