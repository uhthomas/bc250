#!/usr/bin/env python3
"""Compare selector-8 activity across VCPU reset and a proven ring fetch.

The ring memory-read control was calibrated on this exact BC250 in a prior
boot. This candidate measures the same selector with reset asserted, after
reset release, and while replaying that ring fetch. The event's architectural
meaning is unknown; a zero VCPU-window count is not proof of no VCPU reads.
Only volatile registers on the guarded diagnostic kernel are changed.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-perfmon-control-20260929/vcn_v2_0.c'
SOURCE_SHA = '5b6bc1ba51ebb308cebe9a8b4ac3bd855307595a206e07d2205594833c7b2e9b'
DEST = BUILD / 'vcn-rbc-perfmon-phase-20260929'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'

RESET_OLD = '''\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET,
\t\t\t\t UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\tudelay(10);
\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET, 0);'''
RESET_NEW = '''\t\t/* Calibrate the same selector on either side of reset release.
\t\t * Keep the VCPU held for the baseline. Reset the counter between
\t\t * windows so the second reading cannot include the first one.
\t\t */
\t\tif (RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL) != 0)
\t\t\treturn -EINVAL;
\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET,
\t\t\t\t UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\tudelay(10);
\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 0x800);
\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 0x801);
\t\tmdelay(20);
\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 0x802);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN perfmon phase held: ctrl=%08x lo=%08x hi=%08x status=%08x pf=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_LO),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_HI),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS));
\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 0x800);
\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 0x801);
\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET, 0);'''

REQUESTS_END = '''\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS));
\t}

\tif (adev->pdev->device == 0x13fe) {
\t\tu32 power = RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS);'''
RELEASE_LOG = '''\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 0x802);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN perfmon phase released: ctrl=%08x lo=%08x hi=%08x status=%08x pf=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_LO),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_HI),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS));
\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 0);
'''


def substitute(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'VCN perfmon phase anchor changed: {old[:60]!r}')
    return source.replace(old, new, 1)


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned perfmon control source changed')
    source = data.decode()
    source = substitute(source, RESET_OLD, RESET_NEW)
    source = substitute(source, REQUESTS_END,
                        REQUESTS_END.replace('\t}\n\n\tif',
                                             RELEASE_LOG + '\t}\n\n\tif', 1))
    vcn = BUILD / 'vcn-rbc-perfmon-control-20260929/amdgpu_vcn.c'
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
