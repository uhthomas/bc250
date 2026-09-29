#!/usr/bin/env python3
"""Add a bounded VCN-local perfmon scan to the pinned LMI request probe.

Event-selector meanings are undocumented in the available VCN 2.0 headers.
Nonzero counts show that the monitor is live; zero counts are inconclusive.
This changes only volatile debug-counter controls on the diagnostic kernel.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-memory-requests-20260929/vcn_v2_0.c'
SOURCE_SHA = '26b58c21fa8e695d0e5356902a19f48d22b186995a962efa3bb53b81078b51a3'
DEST = BUILD / 'vcn-lmi-perfmon-20260929'
PRE = '\t/* On this BC250 UVD_SOFT_RESET reads as all ones. Avoid carrying\n'
POST = '\tfor (i = 0; i < 10; ++i) {\n'


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned LMI source changed')
    source = data.decode()
    if source.count(PRE) != 1 or source.count(POST) != 1:
        raise ValueError('VCN startup anchors changed')
    pre = '''\tif (adev->pdev->device == 0x13fe) {
\t\tu32 perf = RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL);

\t\t/* Navi10 PERFMON_STATE: RESET=0, START=1, FREEZE=2.
\t\t * Selector zero covers the VCPU release instant; the selector's
\t\t * event meaning is deliberately left unknown.
\t\t */
\t\tif (perf != 0 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS) != 0x800 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS) != 0)
\t\t\treturn -EINVAL;
\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 0);
\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 1);
\t\tif (RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL) != 1)
\t\t\treturn -EIO;
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN perfmon armed: ctrl=%08x lo=%08x hi=%08x credits=%08x sph=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_LO),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_HI),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_MC_CREDITS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_SPH));
\t}

'''
    post = '''\tif (adev->pdev->device == 0x13fe) {
\t\tunsigned int selector;
\t\tu32 nonzero = 0;

\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 2);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN perfmon release: ctrl=%08x lo=%08x hi=%08x credits=%08x sph=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_LO),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_HI),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_MC_CREDITS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_SPH));
\t\tfor (selector = 1; selector < 32; ++selector) {
\t\t\tu32 control = selector << 8;
\t\t\tu32 lo, hi, observed;

\t\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, control);
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, control | 1);
\t\t\tmdelay(2);
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, control | 2);
\t\t\tobserved = RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL);
\t\t\tlo = RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_LO);
\t\t\thi = RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_HI);
\t\t\tnonzero += lo != 0 || hi != 0;
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN perfmon selector=%u ctrl=%08x lo=%08x hi=%08x\\n",
\t\t\t\t selector, observed, lo, hi);
\t\t}\n\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL, 0);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN perfmon done: nonzero_selectors=%u restored=%08x credits=%08x sph=%08x\\n",
\t\t\t nonzero, RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_MC_CREDITS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_SPH));
\t}\n
'''
    source = source.replace(PRE, pre + PRE, 1)
    source = source.replace(POST, post + POST, 1)
    DEST.mkdir(parents=True, exist_ok=True)
    vcn = BUILD / 'vcn-memory-requests-20260929/amdgpu_vcn.c'
    if hashlib.sha256(vcn.read_bytes()).hexdigest() != (
            '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'):
        raise ValueError('pinned amdgpu_vcn.c changed')
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
