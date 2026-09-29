#!/usr/bin/env python3
"""Prepare a private exact-original 20,727-burst Pico control payload.

The data comes from the pinned working BC250 ROM. This only writes ignored
local files; programming the Pico and running the control are separate steps.
"""

import argparse
import hashlib
import json
from pathlib import Path


WORKING_SHA256 = 'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183'
ROM_START = 0xAEDE80
ROM_END = 0xC31C40
PICO_FLASH_OFFSET = 0x200000
BLOCK_BYTES = 64
SECTOR_BYTES = 4096


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(working: bytes) -> tuple[bytes, str, dict]:
    if len(working) != 0x1000000 or digest(working) != WORKING_SHA256:
        raise ValueError('working ROM size or SHA256 mismatch')
    original = working[ROM_START:ROM_END]
    if len(original) != 20727 * BLOCK_BYTES:
        raise AssertionError('unexpected original UEFI stream length')
    padded_length = (len(original) + SECTOR_BYTES - 1) // SECTOR_BYTES * SECTOR_BYTES
    payload = original + b'\xff' * (padded_length - len(original))
    if len(payload) != 1327104:
        raise AssertionError('unexpected Pico QSPI payload length')
    payload_digest = digest(payload)
    hash_bytes = bytes.fromhex(payload_digest)
    header = [
        '#ifndef BC250_DF_LOCK_SAME_LENGTH_PAYLOAD_H',
        '#define BC250_DF_LOCK_SAME_LENGTH_PAYLOAD_H',
        '#include <stdint.h>',
        '#define DF_LOCK_PROFILE_NAME "exact-original-two-pass-control-v01"',
        '#define DF_LOCK_PAYLOAD_SHA256_BYTES \\',
    ]
    for offset in range(0, len(hash_bytes), 8):
        end = ' \\' if offset + 8 < len(hash_bytes) else ''
        header.append('    ' + ', '.join(f'0x{byte:02x}' for byte in hash_bytes[offset:offset + 8]) + ',' + end)
    header += [
        f'#define DF_LOCK_ROM_START 0x{ROM_START:08x}u',
        f'#define DF_LOCK_ROM_END 0x{ROM_END:08x}u',
        '#define DF_LOCK_BLOCK_COUNT 20727u',
        f'#define DF_LOCK_PICO_FLASH_OFFSET 0x{PICO_FLASH_OFFSET:08x}u',
        'static const uint32_t df_lock_first_words[DF_LOCK_BLOCK_COUNT] = {',
    ]
    words = [int.from_bytes(original[i:i + 4], 'big')
             for i in range(0, len(original), BLOCK_BYTES)]
    for offset in range(0, len(words), 8):
        header.append('    ' + ', '.join(f'0x{word:08x}u' for word in words[offset:offset + 8]) + ',')
    header += ['};', '#endif', '']
    report = {
        'purpose': 'exact-original full-stream SPI control, no BC250 EEPROM write',
        'working_rom_sha256': WORKING_SHA256,
        'rom_start': f'{ROM_START:06x}',
        'rom_end_exclusive': f'{ROM_END:06x}',
        'response_blocks_per_pass': len(words),
        'padded_payload_bytes': len(payload),
        'payload_sha256': payload_digest,
        'header_sha256': digest('\n'.join(header).encode()),
        'bios_flash_written': False,
        'pico_flash_written': False,
        'hardware_tested': False,
    }
    return payload, '\n'.join(header), report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--working-rom', required=True, type=Path)
    parser.add_argument('--out-dir', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2] / 'output'
    try:
        args.out_dir.resolve().relative_to(root.resolve())
    except ValueError:
        parser.error('out-dir must be under the private ignored output/ tree')
    payload, header, report = build(args.working_rom.read_bytes())
    args.out_dir.mkdir(parents=True, exist_ok=False)
    (args.out_dir / 'original-qspi-payload.bin').write_bytes(payload)
    (args.out_dir / 'df_lock_same_length_payload.h').write_text(header)
    (args.out_dir / 'original-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
