#!/usr/bin/env python3
"""Enable VCPU PC trace through the calibrated 0x1d8 ring address.

The first packet sets only TRCE_EN, then a scratch marker.  After a bounded
PC sample, the second packet restores the pinned control word, followed by a
host restore fallback.  The outer trial cold-cycles after capture.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-vcpu-clock-mapped-20260929/vcn_v2_0.c'
SOURCE_SHA = '485e8e250c3a0c5c4adc47fc6fbed39a2c713ca877fc975358f83d1927fb1dac'
DEST = BUILD / 'vcn-rbc-vcpu-trace-mapped-20260929'
VALUE_OLD = '0x0ff20200 & ~UVD_VCPU_CNTL__CLK_EN_MASK'
VALUE_NEW = '0x0ff20200 | UVD_VCPU_CNTL__TRCE_EN_MASK'
SECOND_ANCHOR = '\t\tfor (sample_i = 16; sample_i < 32; ++sample_i)\n'
SAMPLE = '''\t\t{
\t\t\tu32 first = RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE);
\t\t\tu32 last = first, pc_and = first, pc_or = first;
\t\t\tu32 changes = 0;

\t\t\tfor (sample_i = 0; sample_i < 4096; ++sample_i) {
\t\t\t\tu32 pc = RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE);

\t\t\t\tchanges += pc != last;
\t\t\t\tpc_and &= pc;
\t\t\t\tpc_or |= pc;
\t\t\t\tlast = pc;
\t\t\t\tudelay(5);
\t\t\t}
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN RBC VCPU mapped trace sample: first=%08x last=%08x and=%08x or=%08x changes=%u cntl=%08x status=%08x pf=%08x\\n",
\t\t\t\t first, last, pc_and, pc_or, changes,
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS));
\t\t}

'''


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned mapped VCPU clock source changed')
    source = data.decode()
    if source.count(VALUE_OLD) != 1 or source.count(SECOND_ANCHOR) != 1:
        raise ValueError('mapped trace anchors changed')
    source = source.replace(VALUE_OLD, VALUE_NEW, 1)
    source = source.replace(SECOND_ANCHOR, SAMPLE + SECOND_ANCHOR, 1)
    source = source.replace('BC250 VCN RBC VCPU mapped clock ',
                            'BC250 VCN RBC VCPU mapped trace ')
    vcn = BUILD / 'vcn-rbc-vcpu-clock-mapped-20260929/amdgpu_vcn.c'
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
