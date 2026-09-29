#!/usr/bin/env python3
"""Audit the pinned BC250 ABL images and their order in a captured SPI profile.

This reads local files only. A literal absence says nothing about addresses
constructed in instructions, read from tables, or supplied by hardware.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


ROM_SHA = 'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183'
IPL_SHA = '2fe1046cb0ac338d86176bf59e8fdabd574954d1df5892fd8c674e40a2309141'
PROFILE_SHA = 'f1a0c46b57e052f7943f7ab95e678fc3338ca16beaa21f6cabada54b489d7851'
ABL_STARTS = (0x99f700, 0x99fc00, 0x9abb00, 0x9afb00, 0x9b9d00)
ABL_SIGNER_GUID = bytes.fromhex('663ca5220aad4b569fc565d36e2e4ed7')
ABL_SIGNER_RECORD = 0x9db240
TARGETS = {
    'vcn_harvest': 0x1f81c,
    'vcn_policy_first': 0x1f820,
    'vcn_policy_second': 0x1f8a4,
    'candidate_fabric': 0x50d6c,
    'candidate_handshake': 0x511b4,
    'core_mask_control': 0x5a870,
    'ipl_smn_selector': 0x0322003c,
}


def checked_bytes(path, expected_hash):
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_hash:
        raise ValueError(f'{path}: SHA256 {actual}, expected {expected_hash}')
    return data


def literal_offsets(data):
    result = {}
    for name, value in TARGETS.items():
        needle = struct.pack('<I', value)
        positions = [match.start() for match in re.finditer(re.escape(needle), data)]
        if positions:
            result[name] = [hex(position) for position in positions]
    return result


def profile_runs(source):
    marker = 'static const struct expected_run expected_runs[PROFILE_RUNS] = {'
    block = source.split(marker, 1)[1].split('};', 1)[0]
    runs = [(int(start, 16) & 0xffffff, int(count)) for start, count in
            re.findall(r'\{0x([0-9a-f]+)u, (\d+)u\}', block)]
    if len(runs) != 37 or sum(count for _, count in runs) != 872744:
        raise ValueError('captured SPI profile geometry changed')
    return runs


def observed_rows(runs, start, end):
    result = []
    row = 0
    for address, count in runs:
        run_end = address + count * 4
        if address < end and run_end > start:
            result.append([row, row + count - 1])
        row += count
    return result


def abl_record(rom, name, start, runs, signer):
    if rom[start + 0x10:start + 0x14] != b'$PS1':
        raise ValueError(f'{name}: missing $PS1 header')
    if rom[start + 0x38:start + 0x48] != ABL_SIGNER_GUID:
        raise ValueError(f'{name}: unexpected signer GUID')
    decompressed_size = struct.unpack_from('<I', rom, start + 0x50)[0]
    compressed_size = struct.unpack_from('<I', rom, start + 0x54)[0]
    body_size = struct.unpack_from('<I', rom, start + 0x14)[0]
    signed_end = start + 0x100 + body_size
    image_end = signed_end + 0x100
    if not compressed_size <= body_size or image_end > len(rom):
        raise ValueError(f'{name}: invalid image bounds')
    compressed = rom[start + 0x100:start + 0x100 + compressed_size]
    body = zlib.decompress(compressed)
    if len(body) != decompressed_size:
        raise ValueError(f'{name}: decompressed length mismatch')
    body_sha = hashlib.sha256(body).digest()
    if rom[start + 0xd0:start + 0xf0] != body_sha:
        raise ValueError(f'{name}: decompressed digest mismatch')
    signer.verify(rom[signed_end:image_end], rom[start:signed_end],
                  padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                  hashes.SHA256())
    rows = observed_rows(runs, start, image_end)
    if not rows:
        raise ValueError(f'{name}: signed image absent from SPI read profile')
    return {
        'flash_start': hex(start),
        'signed_image_end': hex(image_end),
        'compressed_bytes': compressed_size,
        'decompressed_bytes': len(body),
        'decompressed_sha256': body_sha.hex(),
        'read_row_ranges': rows,
        'direct_little_endian_literals': literal_offsets(body),
        'vendor_signature_verified': True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--ipl', type=Path, required=True)
    parser.add_argument('--profile', type=Path, required=True)
    args = parser.parse_args()
    rom = checked_bytes(args.rom, ROM_SHA)
    ipl = checked_bytes(args.ipl, IPL_SHA)
    runs = profile_runs(checked_bytes(args.profile, PROFILE_SHA).decode())
    if len(rom) != 0x1000000 or len(ipl) != 0xa800:
        raise ValueError('unexpected ROM or IPL size')
    if struct.unpack_from('<I', rom, ABL_SIGNER_RECORD)[0] != 0x150 or \
            struct.unpack_from('<I', rom, ABL_SIGNER_RECORD + 8)[0] != 42:
        raise ValueError('usage-42 ABL signer record moved')
    modulus = int.from_bytes(rom[ABL_SIGNER_RECORD + 0x50:
                                 ABL_SIGNER_RECORD + 0x150], 'little')
    signer = rsa.RSAPublicNumbers(65537, modulus).public_key()
    abls = {f'ABL{index}': abl_record(rom, f'ABL{index}', start, runs, signer)
            for index, start in enumerate(ABL_STARTS)}
    print(json.dumps({
        'rom_sha256': ROM_SHA,
        'ipl_sha256': IPL_SHA,
        'profile_sha256': PROFILE_SHA,
        'ipl_direct_little_endian_literals': literal_offsets(ipl),
        'abl_images': abls,
        'limitation': 'SPI read order is not proof of execution order; absent '
                      'literal does not rule out computed or hardware-derived addresses.',
    }, indent=2))


if __name__ == '__main__':
    main()
