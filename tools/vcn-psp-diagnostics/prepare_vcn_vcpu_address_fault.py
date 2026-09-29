#!/usr/bin/env python3
"""Probe VCPU address-error status with firmware BAR beyond measured VRAM.

The 512 MiB VRAM aperture ends at F4:1fffffff on this BC250. The ring
temporarily sets BAR_LOW=0x20080000 while VCPU reset is held. A signed PSP
read checks the low 20 bits of that mismatch before release. The ring then
releases VCPU reset for one bounded window, restores the authenticated BAR,
and the PSP checks the full map and reset state before signed replay.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-fetch-bar-differential-20260929/vcn_v2_0.c'
SOURCE_SHA = '29f90692e8b0ec1decebcaaa6846293cad00af318b6dbbca5e0c4aae5eecbe35'
VCN = BUILD / 'vcn-fetch-bar-differential-20260929/amdgpu_vcn.c'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'
DEST = BUILD / 'vcn-vcpu-address-fault-20260929'


def replace_n(source: str, old: str, new: str, expected: int) -> str:
    count = source.count(old)
    if count != expected:
        raise ValueError(f'address-fault anchor count {count}!={expected}: {old[:64]!r}')
    return source.replace(old, new)


def main() -> None:
    source = SOURCE.read_bytes()
    vcn = VCN.read_bytes()
    if (hashlib.sha256(source).hexdigest() != SOURCE_SHA or
            hashlib.sha256(vcn).hexdigest() != VCN_SHA):
        raise ValueError('pinned VCPU BAR source changed')
    candidate = source.decode()
    candidate = replace_n(candidate,
        'ring->gpu_addr != 0x264000 || ring->ring_size != 4096 ||',
        'ring->gpu_addr != 0x264000 || ring->ring_size != 4096 ||\n'
        '\t\t    adev->gmc.vram_start != 0xf400000000ULL ||\n'
        '\t\t    adev->gmc.vram_end != 0xf41fffffffULL ||\n'
        '\t\t    adev->gmc.real_vram_size != 0x20000000ULL ||', 1)
    candidate = replace_n(candidate,
        'WRITE_ONCE(ring->ring[5], 0x1fa10000);',
        'WRITE_ONCE(ring->ring[5], 0x20080000);', 1)
    candidate = replace_n(candidate,
        '/* Put cache size back before release so the only deliberately\n'
        '\t\t * wrong firmware-map field during the test is BAR_LOW. The prior\n'
        '\t\t * PSP sentinel has already authenticated the 64 KiB displacement.\n'
        '\t\t */',
        '/* Put cache size back before release so the only deliberately\n'
        '\t\t * wrong firmware-map field during the test is BAR_LOW. The\n'
        '\t\t * PSP sentinel records low 20 bits of its out-of-VRAM value.\n'
        '\t\t */', 1)
    candidate = replace_n(candidate,
        '\t\tfor (sample_i = 16; sample_i < 32; ++sample_i)',
        '\t\tdev_warn(adev->dev,\n'
        '\t\t\t "BC250 VCPU address fault held: sys=%08x en=%08x trce_rd=%08x\\n",\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SYS_INT_STATUS),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SYS_INT_EN),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE_RD));\n'
        '\t\tfor (sample_i = 16; sample_i < 32; ++sample_i)', 1)
    candidate = replace_n(candidate,
        'u32 pf_or = RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS);',
        'u32 sys_or = RREG32_SOC15(UVD, 0, mmUVD_SYS_INT_STATUS);', 2)
    candidate = replace_n(candidate,
        'pf_or |= RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS);',
        'sys_or |= RREG32_SOC15(UVD, 0, mmUVD_SYS_INT_STATUS);', 2)
    candidate = replace_n(candidate,
        'pc_or=%08x pf_or=%08x status=%08x pc=%08x pf=%08x prid=%08x lmi=%08x latency=%08x\\n",',
        'pc_or=%08x sys_or=%08x status=%08x pc=%08x sys=%08x prid=%08x lmi=%08x latency=%08x trce_rd=%08x\\n",',
        2)
    candidate = replace_n(candidate,
        'status0, status_or, pc_or, pf_or,',
        'status0, status_or, pc_or, sys_or,', 2)
    candidate = replace_n(candidate,
        '\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS),\n'
        '\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),',
        '\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SYS_INT_STATUS),\n'
        '\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),', 2)
    candidate = replace_n(candidate,
        '\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_STATUS),\n'
        '\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CNTR));',
        '\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_STATUS),\n'
        '\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CNTR),\n'
        '\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE_RD));', 2)
    candidate = replace_n(candidate,
        'BC250 VCPU fetch differential displaced:',
        'BC250 VCPU address fault displaced:', 1)
    candidate = replace_n(candidate,
        'BC250 VCPU fetch differential restored:',
        'BC250 VCPU address fault restored:', 1)
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in (('vcn_v2_0.c', candidate.encode()),
                       ('amdgpu_vcn.c', vcn)):
        path = DEST / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_bytes(data)
        print(name, hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    main()
