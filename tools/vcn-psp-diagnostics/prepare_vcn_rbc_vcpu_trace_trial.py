#!/usr/bin/env python3
"""Try VCPU trace enable through the proven VCN ring packet path.

The packet writes the pinned UVD_VCPU_CNTL value with only TRCE_EN added,
then writes SCRATCH9 as an execution marker. All changes are volatile and
the diagnostic trial cold-cycles the board after capture.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-direct-packet-20260929/vcn_v2_0.c'
SOURCE_SHA = '9ca8ab8b4338494063daafaee19aff1c0e2d1497594f3abc9ec55356c41e102e'
DEST = BUILD / 'vcn-rbc-vcpu-trace-20260929'


def substitute(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'VCN probe anchor changed: {old[:60]!r}')
    return source.replace(old, new, 1)


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned RBC packet source changed')
    source = data.decode()
    source = substitute(source,
        '''\t\t    ring->gpu_addr != 0x264000 || ring->ring_size != 4096) {''',
        '''\t\t    ring->gpu_addr != 0x264000 || ring->ring_size != 4096 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != 0x0ff20200) {''')
    source = substitute(source,
        '''\t\t/* Try the scratch write as the first packet, without the
\t\t * firmware-mediated GPCOM packet-start command. Pad to 16 dwords.
\t\t */
\t\tWRITE_ONCE(ring->ring[0], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[1], 0xdeadbeef);
\t\tfor (sample_i = 2; sample_i < 16; ++sample_i)
''',
        '''\t\t/* A successful SCRATCH9 packet established that 0xc000-prefixed
\t\t * VCN register writes execute through this ring. Change only the
\t\t * documented trace-enable bit before the scratch marker.
\t\t */
\t\tWRITE_ONCE(ring->ring[0], PACKET0(0xc000 | mmUVD_VCPU_CNTL, 0));
\t\tWRITE_ONCE(ring->ring[1],
\t\t\t   0x0ff20200 | UVD_VCPU_CNTL__TRCE_EN_MASK);
\t\tWRITE_ONCE(ring->ring[2], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
\t\tWRITE_ONCE(ring->ring[3], 0xdeadbeef);
\t\tfor (sample_i = 4; sample_i < 16; ++sample_i)
''')
    source = substitute(source,
        '''\t\t/* With NO_FETCH set and NO_UPDATE clear, a WPTR write should''',
        '''\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN RBC VCPU trace pre: cntl=%08x pc=%08x status=%08x packet=%08x value=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS),
\t\t\t READ_ONCE(ring->ring[0]), READ_ONCE(ring->ring[1]));

\t\t/* With NO_FETCH set and NO_UPDATE clear, a WPTR write should''')
    source = substitute(source,
        '''\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, run_cntl);
\t\trptr_first = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);''',
        '''\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN RBC VCPU trace hold: cntl=%08x pc=%08x status=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS));
\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, run_cntl);
\t\trptr_first = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);''')
    source = substitute(source,
        '''\t\tif (!(RREG32_SOC15(UVD, 0, mmUVD_STATUS) & 2)) {''',
        '''\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN RBC VCPU trace execute: cntl=%08x pc=%08x status=%08x scratch=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9));
\t\tif (!(RREG32_SOC15(UVD, 0, mmUVD_STATUS) & 2)) {''')
    DEST.mkdir(parents=True, exist_ok=True)
    vcn = BUILD / 'vcn-rbc-direct-packet-20260929/amdgpu_vcn.c'
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
