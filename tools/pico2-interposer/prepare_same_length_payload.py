#!/usr/bin/env python3
"""Prepare a private Pico-QSPI payload for an UNTESTED DF-lock trial.

This only writes local ignored files. It does not program either flash chip.
The 4 MB Pico-flash backup must show the reserved destination as erased.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path


CANDIDATE_SHA256 = 'ae9145cfa521107ebb7e553c39877a89f822ea1960e16f83a38485b9b5fe2331'
PICO_BACKUP_SHA256 = '2f9c05f13b8b2c177b5ba212d7e02418c941dfc906939f4505c4954daa27fbc1'
ROM_START = 0xAEDE80
ROM_END = 0xC31C40
PICO_FLASH_OFFSET = 0x200000
BLOCK = 64
SECTOR = 4096


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bench_header(payload: bytes) -> str:
    if len(payload) != 1327104 or digest(payload) != (
            '94693ac43e90236b77e6fc2be64c4ab8e48e18fd88b0ec6c3b95ae9af1e53ef9'):
        raise ValueError('unpinned payload for XIP bench')
    words = [int.from_bytes(payload[i:i + 4], 'big') for i in range(0, 64, 4)]
    return '\n'.join((
        '#ifndef BC250_DF_LOCK_XIP_EXPECTED_H',
        '#define BC250_DF_LOCK_XIP_EXPECTED_H',
        '#define SOURCE_OFFSET 0x200000u',
        'static const uint32_t expected_source_words[16] = {',
        '    ' + ', '.join(f'0x{word:08x}u' for word in words[:8]) + ',',
        '    ' + ', '.join(f'0x{word:08x}u' for word in words[8:]) + ',',
        '};',
        '#endif',
        '',
    ))


def build(candidate: bytes, pico_backup: bytes) -> tuple[bytes, str, dict]:
    if len(candidate) != 0x1000000 or digest(candidate) != CANDIDATE_SHA256:
        raise ValueError('same-length candidate size or SHA256 mismatch')
    if len(pico_backup) != 0x400000 or digest(pico_backup) != PICO_BACKUP_SHA256:
        raise ValueError('Pico flash backup size or SHA256 mismatch')
    blocks = (ROM_END - ROM_START) // BLOCK
    if ROM_START % BLOCK or ROM_END % BLOCK or blocks != 20727:
        raise AssertionError('unpinned overlay address window')
    raw = candidate[ROM_START:ROM_END]
    padded_size = (len(raw) + SECTOR - 1) // SECTOR * SECTOR
    if any(byte != 0xff for byte in pico_backup[
            PICO_FLASH_OFFSET:PICO_FLASH_OFFSET + padded_size]):
        raise ValueError('Pico destination was not erased in pinned backup')
    payload = raw + b'\xff' * (padded_size - len(raw))
    words = [int.from_bytes(raw[i:i + 4], 'big') for i in range(0, len(raw), BLOCK)]
    lines = [
        '#ifndef BC250_DF_LOCK_SAME_LENGTH_PAYLOAD_H',
        '#define BC250_DF_LOCK_SAME_LENGTH_PAYLOAD_H',
        '#include <stdint.h>',
        f'#define DF_LOCK_ROM_START 0x{ROM_START:08x}u',
        f'#define DF_LOCK_ROM_END 0x{ROM_END:08x}u',
        f'#define DF_LOCK_BLOCK_COUNT {blocks}u',
        f'#define DF_LOCK_PICO_FLASH_OFFSET 0x{PICO_FLASH_OFFSET:08x}u',
        'static const uint32_t df_lock_first_words[DF_LOCK_BLOCK_COUNT] = {',
    ]
    for i in range(0, len(words), 8):
        lines.append('    ' + ', '.join(f'0x{word:08x}u' for word in words[i:i + 8]) + ',')
    lines += ['};', '#endif', '']
    header = '\n'.join(lines)
    report = dict(purpose='offline reversible interposer payload; UNTESTED DF-lock candidate',
                  candidate_sha256=CANDIDATE_SHA256,
                  pico_backup_sha256=PICO_BACKUP_SHA256,
                  rom_start=f'{ROM_START:06x}', rom_end_exclusive=f'{ROM_END:06x}',
                  pico_flash_offset=f'{PICO_FLASH_OFFSET:06x}',
                  response_blocks=blocks, response_bytes=len(raw),
                  padded_payload_bytes=len(payload),
                  payload_sha256=digest(payload), header_sha256=digest(header.encode()),
                  bios_flash_written=False, pico_flash_written=False,
                  hardware_tested=False)
    return payload, header, report


def private_create(path: Path, payload: bytes) -> None:
    if 'output' not in path.parts:
        raise ValueError('private payload must stay under ignored output/')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-rom', required=True, type=Path)
    parser.add_argument('--pico-flash-backup', required=True, type=Path)
    parser.add_argument('--payload', required=True, type=Path)
    parser.add_argument('--header', required=True, type=Path)
    parser.add_argument('--bench-header', type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    paths = (args.payload, args.header, args.report)
    if args.bench_header:
        paths += (args.bench_header,)
    if any('output' not in path.parts or path.exists() for path in paths):
        parser.error('all outputs must be new private files under output/')
    payload, header, report = build(args.candidate_rom.read_bytes(),
                                    args.pico_flash_backup.read_bytes())
    private_create(args.payload, payload)
    private_create(args.header, header.encode())
    if args.bench_header:
        private_create(args.bench_header, bench_header(payload).encode())
    private_create(args.report, (json.dumps(report, indent=2) + '\n').encode())
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
