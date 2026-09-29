#!/usr/bin/env python3
"""Program the pinned BO cache window through VCN ring-internal offsets.

The first aligned group holds VCPU reset, writes the already PSP-verified
firmware BO cache window, and marks completion.  After a bounded hold, the
second group releases VCPU reset.  Every value matches the pinned Linux BO
layout; the trial cold-cycles afterward.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-vcpu-reset-mapped-20260929/vcn_v2_0.c'
SOURCE_SHA = 'e5fde867ccd88198b7f403172788c11859610111d9b5d1a46fc65bf2abb57314'
DEST = BUILD / 'vcn-rbc-cache-map-20260929'

GUARD_OLD = '''\t\t    ring->gpu_addr != 0x264000 || ring->ring_size != 4096 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != 0x0ff20200) {'''
GUARD_NEW = '''\t\t    ring->gpu_addr != 0x264000 || ring->ring_size != 4096 ||
\t\t    adev->vcn.inst[0].gpu_addr != 0xf41fc00000ULL ||
\t\t    !adev->vcn.inst[0].fw ||
\t\t    AMDGPU_GPU_PAGE_ALIGN(adev->vcn.inst[0].fw->size + 4) != 0x64000 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != 0x0ff20200) {'''
FIRST_OLD = '''\t\t/* A successful SCRATCH9 packet established that 0xc000-prefixed
\t\t * VCN register writes execute through this ring. Change only the
\t\t * documented trace-enable bit before the scratch marker.
\t\t */
\t\tWRITE_ONCE(ring->ring[0], PACKET0(mmUVD_SOFT_RESET - 0x80, 0));
\t\tWRITE_ONCE(ring->ring[1],
\t\t\t   UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\tWRITE_ONCE(ring->ring[2], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[3], 0x11112222);
\t\tfor (sample_i = 4; sample_i < 16; ++sample_i)
'''
FIRST_NEW = '''\t\t/* The 0x1d8 clock-control calibration proved the segment-1 ring
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
\t\tWRITE_ONCE(ring->ring[9],
\t\t\t   AMDGPU_GPU_PAGE_ALIGN(adev->vcn.inst[0].fw->size + 4));
\t\tWRITE_ONCE(ring->ring[10], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[11], 0x11112222);
\t\tfor (sample_i = 12; sample_i < 16; ++sample_i)
'''
PREFIX_OLD = 'BC250 VCN RBC VCPU mapped reset '
PREFIX_NEW = 'BC250 VCN RBC cache map '
AFTER_FIRST = '''\t\tfor (sample_i = 16; sample_i < 32; ++sample_i)
'''
CACHE_READ = '''\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN RBC cache map host read: high=%08x low=%08x offset=%08x size=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_VCPU_CACHE_64BIT_BAR_HIGH),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_VCPU_CACHE_64BIT_BAR_LOW),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_CACHE_OFFSET0),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_CACHE_SIZE0));

'''


def substitute(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'VCN probe anchor changed: {old[:55]!r}')
    return source.replace(old, new, 1)


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned ring reset source changed')
    source = data.decode()
    source = substitute(source, GUARD_OLD, GUARD_NEW)
    source = substitute(source, FIRST_OLD, FIRST_NEW)
    source = substitute(source, AFTER_FIRST, CACHE_READ + AFTER_FIRST)
    source = source.replace(PREFIX_OLD, PREFIX_NEW)
    vcn = BUILD / 'vcn-rbc-vcpu-reset-mapped-20260929/amdgpu_vcn.c'
    if hashlib.sha256(vcn.read_bytes()).hexdigest() != (
            '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'):
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
