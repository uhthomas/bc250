#!/usr/bin/env python3
"""Enable VCPU PC trace through host MMIO before the guarded reset release.

The prior ring-packet route did not reach VCPU_CNTL.  This probe uses the
already calibrated host-MMIO route and changes only TRCE_EN.  It samples the
PC register after the existing PSP/VCN reset-release sequence, then restores
the original control word.  All changes are volatile.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-memory-requests-20260929/vcn_v2_0.c'
SOURCE_SHA = '26b58c21fa8e695d0e5356902a19f48d22b186995a962efa3bb53b81078b51a3'
VCN = BUILD / 'vcn-memory-requests-20260929/amdgpu_vcn.c'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'
DEST = BUILD / 'vcn-host-vcpu-trace-20260929'

BEFORE = '''\t/* On this BC250 UVD_SOFT_RESET reads as all ones. Avoid carrying'''
SAMPLE = '''\tif (adev->pdev->device == 0x13fe) {
\t\tu32 before = RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL);
\t\tu32 power = RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS);
\t\tu32 pgfsm = RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS);

\t\tif (power != 0x800 || pgfsm != 0 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_VERSION) != 0x2001b ||
\t\t    before != 0x0ff20200)
\t\t\treturn -EINVAL;
\t\tWREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL,
\t\t\t\t before | UVD_VCPU_CNTL__TRCE_EN_MASK);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN host trace armed: before=%08x after=%08x prid=%08x pc=%08x status=%08x\\n",
\t\t\t before, RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS));
\t\tif (RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) !=
\t\t    (before | UVD_VCPU_CNTL__TRCE_EN_MASK)) {
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL, before);
\t\t\treturn -EIO;
\t\t}
\t}

'''

AFTER = '''\tfor (i = 0; i < 10; ++i) {
'''
MEASURE = '''\tif (adev->pdev->device == 0x13fe) {
\t\tu32 first, last, pc_and, pc_or, changes = 0;
\t\tu32 status_or = 0;
\t\tunsigned int sample_i;

\t\tfirst = RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE);
\t\tlast = pc_and = pc_or = first;
\t\tfor (sample_i = 0; sample_i < 4096; ++sample_i) {
\t\t\tu32 pc = RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE);

\t\t\tchanges += pc != last;
\t\t\tpc_and &= pc;
\t\t\tpc_or |= pc;
\t\t\tlast = pc;
\t\t\tstatus_or |= RREG32_SOC15(UVD, 0, mmUVD_STATUS);
\t\t\tudelay(5);
\t\t}
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN host trace result: first=%08x last=%08x and=%08x or=%08x changes=%u status_or=%08x cntl=%08x prid=%08x pf=%08x lmi=%08x\\n",
\t\t\t first, last, pc_and, pc_or, changes, status_or,
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_STATUS));
\t\tWREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL, 0x0ff20200);
\t\tdev_warn(adev->dev, "BC250 VCN host trace restored: cntl=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL));
\t}

'''


def substitute(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'VCN probe anchor changed: {old[:60]!r}')
    return source.replace(old, new, 1)


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned VCN memory-request source changed')
    vcn = VCN.read_bytes()
    if hashlib.sha256(vcn).hexdigest() != VCN_SHA:
        raise ValueError('pinned amdgpu_vcn source changed')
    source = substitute(data.decode(), BEFORE, SAMPLE + BEFORE)
    source = substitute(source, AFTER, MEASURE + AFTER)
    DEST.mkdir(parents=True, exist_ok=True)
    for name, contents in (('vcn_v2_0.c', source),
                           ('amdgpu_vcn.c', vcn.decode())):
        path = DEST / name
        if path.exists() and path.read_text() != contents:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_text(contents)
        print(name, hashlib.sha256(contents.encode()).hexdigest())


if __name__ == '__main__':
    main()
