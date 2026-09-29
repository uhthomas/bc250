#!/usr/bin/env python3
"""Calibrate VCPU_CNTL ring addressing with its known-writable CLK_EN bit.

Two 16-dword ring submissions clear, then restore only CLK_EN. Distinct
SCRATCH9 markers prove whether each packet group executed. A final host
write restores the pinned control value if the second packet does not.
The outer diagnostic harness cold-cycles the board afterward.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-vcpu-trace-20260929/vcn_v2_0.c'
SOURCE_SHA = '816960c3767c001221cb8a3c326c868f951fd70f136c82b50eb526a2bd1916b5'
DEST = BUILD / 'vcn-rbc-vcpu-clock-20260929'


def substitute(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'VCN probe anchor changed: {old[:60]!r}')
    return source.replace(old, new, 1)


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned RBC VCPU trace source changed')
    source = data.decode()
    source = substitute(source,
        '''\t\tWRITE_ONCE(ring->ring[1],
\t\t\t   0x0ff20200 | UVD_VCPU_CNTL__TRCE_EN_MASK);
\t\tWRITE_ONCE(ring->ring[2], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[3], 0xdeadbeef);''',
        '''\t\tWRITE_ONCE(ring->ring[1],
\t\t\t   0x0ff20200 & ~UVD_VCPU_CNTL__CLK_EN_MASK);
\t\tWRITE_ONCE(ring->ring[2], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[3], 0x11112222);''')
    source = source.replace('BC250 VCN RBC VCPU trace ',
                            'BC250 VCN RBC VCPU clock ')
    source = substitute(source,
        '''\t\tif (!(RREG32_SOC15(UVD, 0, mmUVD_STATUS) & 2)) {''',
        '''\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN RBC VCPU clock first: cntl=%08x rptr=%08x scratch=%08x status=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS));
\t\tfor (sample_i = 16; sample_i < 32; ++sample_i)
\t\t\tWRITE_ONCE(ring->ring[sample_i], sample_i & 1 ? 0 :
\t\t\t\t   PACKET0(adev->vcn.inst[0].internal.nop, 0));
\t\tWRITE_ONCE(ring->ring[16], PACKET0(0xc000 | mmUVD_VCPU_CNTL, 0));
\t\tWRITE_ONCE(ring->ring[17], 0x0ff20200);
\t\tWRITE_ONCE(ring->ring[18], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[19], 0x33334444);
\t\twmb();
\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 32);
\t\tfor (sample_i = 0; sample_i < 1024; ++sample_i) {
\t\t\tif (RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR) == 32 &&
\t\t\t    RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9) == 0x33334444)
\t\t\t\tbreak;
\t\t\tudelay(5);
\t\t}
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN RBC VCPU clock second: cntl=%08x rptr=%08x scratch=%08x status=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS));
\t\tif (RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != 0x0ff20200) {
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL, 0x0ff20200);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN RBC VCPU clock host restore: cntl=%08x\\n",
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL));
\t\t}
\t\tif (!(RREG32_SOC15(UVD, 0, mmUVD_STATUS) & 2)) {''')
    DEST.mkdir(parents=True, exist_ok=True)
    vcn = BUILD / 'vcn-rbc-vcpu-trace-20260929/amdgpu_vcn.c'
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
