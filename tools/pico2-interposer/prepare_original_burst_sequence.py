#!/usr/bin/env python3
"""Make an ignored, exact-original 16-burst control header from the pinned ROM.

The generated firmware substitutes no changed bytes and must be loaded into
Pico RAM only. The working ROM and generated header stay under ignored output/.
"""
import argparse
import hashlib
from pathlib import Path


CONTROL_SHA256 = 'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183'
START = 0xAE0140
COUNT = 16
WORDS_PER_BURST = 16


def generate(rom: bytes) -> str:
    if len(rom) != 16 * 1024 * 1024:
        raise ValueError('expected a complete 16 MiB control ROM')
    digest = hashlib.sha256(rom).hexdigest()
    if digest != CONTROL_SHA256:
        raise ValueError(f'working ROM hash mismatch: {digest}')
    lines = [
        '#ifndef BC250_BURST_SEQUENCE_ORIGINAL_H',
        '#define BC250_BURST_SEQUENCE_ORIGINAL_H',
        '#include <stdint.h>',
        f'#define ORIGINAL_SEQUENCE_START 0x{START:08x}u',
        f'#define ORIGINAL_SEQUENCE_COUNT {COUNT}u',
        f'#define ORIGINAL_SEQUENCE_WORDS {WORDS_PER_BURST}u',
        'static const uint32_t original_sequence_words[ORIGINAL_SEQUENCE_COUNT]',
        '    [ORIGINAL_SEQUENCE_WORDS] = {',
    ]
    for i in range(COUNT):
        data = rom[START + i * 64:START + (i + 1) * 64]
        words = [int.from_bytes(data[j:j + 4], 'big')
                 for j in range(0, 64, 4)]
        lines.append('    {' + ', '.join(f'0x{x:08x}u' for x in words) + '},')
    lines += ['};', '#endif', '']
    return '\n'.join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--working-rom', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if 'output' not in args.out.parts:
        ap.error('generated ROM bytes must stay under ignored output/')
    result = generate(args.working_rom.read_bytes())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(result)
    args.out.chmod(0o600)
    print(f'generated {COUNT} exact-original bursts; header SHA256 '
          f'{hashlib.sha256(result.encode()).hexdigest()}')


if __name__ == '__main__':
    main()
