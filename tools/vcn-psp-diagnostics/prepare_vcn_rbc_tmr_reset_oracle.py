#!/usr/bin/env python3
"""Compare the authenticated TMR firmware map without a ring BAR rewrite.

The signed PSP profile maps firmware cache 0 to TMR and keeps the ordinary
BO stack/context/shared windows. The ring only asserts VCPU reset, changes
cache size temporarily, restores size and releases reset. A PSP marked load
checks all sixteen map words before any replay and samples reset. No flash.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-cache-readback-20260929/vcn_v2_0.c'
SOURCE_SHA = '71c91c8b587c4d3649dca0536893463bef240cb0e97896464c4ef0bf0b3b386e'
DEST = BUILD / 'vcn-rbc-tmr-reset-oracle-20260929'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'

GUARD_OLD = '''\t\t    AMDGPU_GPU_PAGE_ALIGN(adev->vcn.inst[0].fw->size + 4) != 0x64000 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != 0x0ff20200) {'''
GUARD_NEW = '''\t\t    AMDGPU_GPU_PAGE_ALIGN(adev->vcn.inst[0].fw->size + 4) != 0x64000 ||
\t\t    adev->firmware.ucode[AMDGPU_UCODE_ID_VCN].tmr_mc_addr_hi != 0xf4 ||
\t\t    adev->firmware.ucode[AMDGPU_UCODE_ID_VCN].tmr_mc_addr_lo != 0x1fa00000 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != 0x0ff20200) {'''

PACKETS_OLD = '''\t\t/* The 0x1d8 clock-control calibration proved the segment-1 ring
\t\t * mapping is host register offset minus 0x80. Hold VCPU reset while
\t\t * replaying the exact four firmware BO cache-window values.
\t\t */
\t\tWRITE_ONCE(ring->ring[0], PACKET0(mmUVD_SOFT_RESET - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[1], UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\tWRITE_ONCE(ring->ring[2],
\t\t\t   PACKET0(mmUVD_LMI_VCPU_CACHE_64BIT_BAR_HIGH - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[3], upper_32_bits(adev->vcn.inst[0].gpu_addr));
\t\tWRITE_ONCE(ring->ring[4],
\t\t\t   PACKET0(mmUVD_LMI_VCPU_CACHE_64BIT_BAR_LOW - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[5], lower_32_bits(adev->vcn.inst[0].gpu_addr));
\t\tWRITE_ONCE(ring->ring[6], PACKET0(mmUVD_VCPU_CACHE_OFFSET0 - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[7], AMDGPU_UVD_FIRMWARE_OFFSET >> 3);
\t\tWRITE_ONCE(ring->ring[8], PACKET0(mmUVD_VCPU_CACHE_SIZE0 - 0x80, 0));
\t\t/* One page below the pinned 0x64000, after reset-assert packet. */
\t\tWRITE_ONCE(ring->ring[9], 0x63000);
\t\tWRITE_ONCE(ring->ring[10], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[11], 0x11112222);
\t\tfor (sample_i = 12; sample_i < 16; ++sample_i)
\t\t\tWRITE_ONCE(ring->ring[sample_i], sample_i & 1 ? 0 :
\t\t\t\t   PACKET0(adev->vcn.inst[0].internal.nop, 0));'''
PACKETS_NEW = '''\t\t/* Leave the PSP-authenticated TMR BAR and offset untouched.
\t\t * The marked PSP read checks all 16 cache words before replay.
\t\t */
\t\tWRITE_ONCE(ring->ring[0], PACKET0(mmUVD_SOFT_RESET - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[1], UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\tWRITE_ONCE(ring->ring[2], PACKET0(mmUVD_VCPU_CACHE_SIZE0 - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[3], 0x63000);
\t\tWRITE_ONCE(ring->ring[4], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[5], 0x11112222);
\t\tfor (sample_i = 6; sample_i < 16; ++sample_i)
\t\t\tWRITE_ONCE(ring->ring[sample_i], sample_i & 1 ? 0 :
\t\t\t\t   PACKET0(adev->vcn.inst[0].internal.nop, 0));'''


def substitute(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'TMR ring anchor changed: {old[:60]!r}')
    return source.replace(old, new, 1)


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned ring source changed')
    source = data.decode()
    source = substitute(source, GUARD_OLD, GUARD_NEW)
    source = substitute(source, PACKETS_OLD, PACKETS_NEW)
    vcn = BUILD / 'vcn-rbc-cache-readback-20260929/amdgpu_vcn.c'
    if hashlib.sha256(vcn.read_bytes()).hexdigest() != VCN_SHA:
        raise ValueError('pinned amdgpu_vcn.c changed')
    DEST.mkdir(parents=True, exist_ok=True)
    for name, contents in (('vcn_v2_0.c', source),
                           ('amdgpu_vcn.c', vcn.read_text())):
        path = DEST / name
        if path.exists() and path.read_text() != contents:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_text(contents)
        print(name, hashlib.sha256(contents.encode()).hexdigest())


if __name__ == '__main__':
    main()
