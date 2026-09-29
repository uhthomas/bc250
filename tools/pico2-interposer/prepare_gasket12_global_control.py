#!/usr/bin/env python3
"""Select pinned client-12 gasket rows for RAM-only control boots.

The pinned 51-row cave is not a standalone BIOS patch. This preserves its
instructions, transaction-open write, global setup and transaction-close
write. The control-window variant also includes the five writes covering
the BC250 driver's video-control addresses at 0x1f844..0x1f84f.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct


SOURCE_SHA = '403b18277958a7e890805d077c43019e55c2b549e36b99168c0fcb9a6ae39bf4'
TABLE_OFFSET = 0x1c
ROW_COUNT = 51
GLOBAL_INDICES = (0, 1, 2, 3, 4, 47, 48, 49, 50)
CONTROL_WINDOW_INDICES = (17, 18, 19, 20, 21)
EARLY_WINDOW_INDICES = tuple(range(5, 27))
LATE_WINDOW_INDICES = tuple(range(27, 47))
LATE_FIRST_HALF_INDICES = tuple(range(27, 37))
LATE_SECOND_HALF_INDICES = tuple(range(37, 47))
EXPECTED_OPEN = (0x0900c234, 0)
EXPECTED_CLOSE = (0x0900c234, 1)


def prepare(source: bytes, variant: str) -> tuple[bytes, list[tuple[int, int]], tuple[int, ...]]:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned gasket cave hash differs')
    if len(source) != 0x1b8 or source[4:6] != bytes.fromhex('3325'):
        raise ValueError('unexpected cave size or Thumb loop count')
    rows = [struct.unpack_from('<II', source, TABLE_OFFSET + 8 * index)
            for index in range(ROW_COUNT)]
    if rows[0] != EXPECTED_OPEN or rows[-1] != EXPECTED_CLOSE:
        raise ValueError('gasket transaction bounds differ')
    if len({address for address, _ in rows}) != 50:
        raise ValueError('gasket table contains unexpected duplicate addresses')
    windows = {
        'global-only': (),
        'control-window': CONTROL_WINDOW_INDICES,
        'early-windows': EARLY_WINDOW_INDICES,
        'late-windows': LATE_WINDOW_INDICES,
        'early-plus-late-first': EARLY_WINDOW_INDICES + LATE_FIRST_HALF_INDICES,
        'early-plus-late-second': EARLY_WINDOW_INDICES + LATE_SECOND_HALF_INDICES,
        'full-minus-20108': tuple(i for i in range(5, 47)
                                    if i not in range(27, 32)),
        'full-minus-21078': tuple(i for i in range(5, 47)
                                    if i not in range(32, 37)),
        'full-minus-20eb0': tuple(i for i in range(5, 47)
                                    if i not in range(37, 42)),
        'full-minus-1f860': tuple(i for i in range(5, 47)
                                    if i not in range(42, 47)),
        'full': tuple(range(5, 47)),
    }
    indices = (tuple(range(5)) + windows[variant] + tuple(range(47, 51)))
    selected = [rows[index] for index in indices]
    candidate = bytearray(source)
    candidate[4:6] = bytes((len(selected), 0x25))  # movs r5, #row_count
    for index, pair in enumerate(selected):
        struct.pack_into('<II', candidate, TABLE_OFFSET + 8 * index, *pair)
    if candidate[:4] != source[:4] or candidate[6:TABLE_OFFSET] != source[6:TABLE_OFFSET]:
        raise AssertionError('gasket executable instructions changed')
    actual = [struct.unpack_from('<II', candidate, TABLE_OFFSET + 8 * index)
              for index in range(len(selected))]
    if actual != selected or actual[-1] != EXPECTED_CLOSE:
        raise AssertionError('selected gasket table did not serialize')
    return bytes(candidate), selected, indices


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--variant', choices=('global-only', 'control-window',
                                            'early-windows', 'late-windows',
                                            'early-plus-late-first',
                                            'early-plus-late-second',
                                            'full-minus-20108',
                                            'full-minus-21078',
                                            'full-minus-20eb0',
                                            'full-minus-1f860', 'full'),
                        default='global-only')
    args = parser.parse_args()
    candidate, rows, indices = prepare(args.source.read_bytes(), args.variant)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cave = args.output_dir / f'gasket-cave-{args.variant}.bin'
    cave.write_bytes(candidate)
    table = args.output_dir / f'gasket-{args.variant}.inc'
    table.write_text(''.join(f'    .word 0x{a:08x}, 0x{v:08x}\n'
                             for a, v in rows))
    manifest = {
        'purpose': 'RAM-only gasket row control; never flash ROM to EEPROM',
        'variant': args.variant,
        'source_sha256': SOURCE_SHA,
        'cave_sha256': hashlib.sha256(candidate).hexdigest(),
        'executed_original_indices': list(indices),
        'executed_rows': len(rows),
        'omitted_rows': ROW_COUNT - len(rows),
    }
    (args.output_dir / 'variant.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
