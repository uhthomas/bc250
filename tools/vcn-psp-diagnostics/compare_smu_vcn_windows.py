#!/usr/bin/env python3
"""Compare pinned Van Gogh VCN code with captured BC250 SMU SRAM by byte window.

This is a literal-code comparison, not a semantic function matcher. A missing
window cannot prove the corresponding behavior or hardware is absent.
"""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BC_PATH = ROOT / 'output/video-decode-20260922/results/smu-sram.bin'
VG_PATH = ROOT / 'output/video-decode-20260922/sources/shalasere-vcn/firmware/vangogh_smu_full.bin'
BC_SHA = 'b0385d7c8fbbec2aaa1ce7f635df46315847e9965f13879f7c9df9b774a0ccc0'
VG_SHA = 'c4de5edc9eb2a9676b7c9a6811e71fee793192ba7bb340d7f6689c7b7eb89b25'
WINDOW = 16
REGIONS = {
    'vg_smn_read_control': (0x3300, 0x337c),
    'vg_smn_write_control': (0x337c, 0x33f8),
    'vg_vcn_inner': (0x26984, 0x26cb0),
    'vg_vcn_entry': (0x2bf30, 0x2c008),
}


def checked(path, expected, size):
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if len(data) != size or actual != expected:
        raise RuntimeError(f'{path}: wrong image size or SHA256')
    return data


def main():
    bc = checked(BC_PATH, BC_SHA, 0x40000)
    vg = checked(VG_PATH, VG_SHA, 524800)
    # Skip low-diversity byte runs, which can match code, data and padding.
    bc_windows = {bc[i:i + WINDOW]: i for i in range(len(bc) - WINDOW + 1)
                  if len(set(bc[i:i + WINDOW])) > 3}
    regions = {}
    for name, (start, end) in REGIONS.items():
        matches = [(offset, bc_windows[vg[offset:offset + WINDOW]])
                   for offset in range(start, end - WINDOW + 1)
                   if vg[offset:offset + WINDOW] in bc_windows]
        regions[name] = {'start': hex(start), 'end': hex(end),
                         'candidate_windows': end - start - WINDOW + 1,
                         'matching_windows': len(matches),
                         'first_matches': [[hex(a), hex(b)] for a, b in matches[:5]]}
    print(json.dumps({'bc_sha256': BC_SHA, 'vg_sha256': VG_SHA,
                      'window_bytes': WINDOW, 'min_distinct_bytes': 4,
                      'regions': regions, 'semantic_equivalence_tested': False},
                     indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
