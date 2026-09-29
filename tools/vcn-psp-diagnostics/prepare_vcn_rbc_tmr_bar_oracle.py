#!/usr/bin/env python3
"""Prove that a ring packet can change and restore the PSP-visible TMR BAR.

The VCPU is held in reset while the firmware BAR low word is briefly shifted
by 0x10000. The signed PSP read-only oracle must report that exact value at
map index 0. A second ring batch restores the TMR BAR, cache size and reset;
the PSP checks all sixteen words before its normal replay. No flash writes.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-tmr-reset-oracle-20260929/vcn_v2_0.c'
SOURCE_SHA = 'c48f5e06d61d3135f5b5f9c2d546abc85a823da3d25eec1632493da151ba7df7'
VCN = BUILD / 'vcn-rbc-tmr-reset-oracle-20260929/amdgpu_vcn.c'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'
DEST = BUILD / 'vcn-rbc-tmr-bar-oracle-20260929'


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'TMR BAR oracle anchor changed: {old[:72]!r}')
    return source.replace(old, new, 1)


def main() -> None:
    source = SOURCE.read_bytes()
    vcn = VCN.read_bytes()
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA or \
            hashlib.sha256(vcn).hexdigest() != VCN_SHA:
        raise ValueError('pinned TMR source changed')
    text = source.decode()
    text = replace_once(text,
        '''\t\t/* Leave the PSP-authenticated TMR BAR and offset untouched.
\t\t * The marked PSP read checks all 16 cache words before replay.
\t\t */''',
        '''\t\t/* Assert reset before shifting the authenticated TMR BAR.
\t\t * The marked PSP read checks the resulting BAR before replay.
\t\t */''')
    text = replace_once(text,
        '''\t\tWRITE_ONCE(ring->ring[4], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[5], 0x11112222);
\t\tfor (sample_i = 6; sample_i < 16; ++sample_i)''',
        '''\t\tWRITE_ONCE(ring->ring[4],
\t\t\t   PACKET0(mmUVD_LMI_VCPU_CACHE_64BIT_BAR_LOW - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[5], 0x1fa10000);
\t\tWRITE_ONCE(ring->ring[6], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[7], 0x11112222);
\t\tfor (sample_i = 8; sample_i < 16; ++sample_i)''')
    text = replace_once(text,
        '''\t\tWRITE_ONCE(ring->ring[16],
\t\t\t   PACKET0(mmUVD_VCPU_CACHE_SIZE0 - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[17], 0x64000);
\t\tWRITE_ONCE(ring->ring[18], PACKET0(mmUVD_SOFT_RESET - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[19], 0);
\t\tWRITE_ONCE(ring->ring[20], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[21], 0x33334444);''',
        '''\t\tWRITE_ONCE(ring->ring[16],
\t\t\t   PACKET0(mmUVD_LMI_VCPU_CACHE_64BIT_BAR_LOW - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[17], 0x1fa00000);
\t\tWRITE_ONCE(ring->ring[18],
\t\t\t   PACKET0(mmUVD_VCPU_CACHE_SIZE0 - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[19], 0x64000);
\t\tWRITE_ONCE(ring->ring[20], PACKET0(mmUVD_SOFT_RESET - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[21], 0);
\t\tWRITE_ONCE(ring->ring[22], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[23], 0x33334444);''')
    text = replace_once(text,
        '''\t\t/* Measure the restored value before the signed driver's ordinary
\t\t * map replay. Finally replay that map even if the ring result was
\t\t * unexpected, so the temporary size cannot persist in this boot.
\t\t */''',
        '''\t\t/* Read the restored BAR before the signed driver's map replay.
\t\t * Replay that map even if a ring packet failed, so the temporary BAR
\t\t * cannot persist during this boot.
\t\t */''')
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in (('vcn_v2_0.c', text.encode()), ('amdgpu_vcn.c', vcn)):
        path = DEST / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_bytes(data)
        print(name, hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    main()
