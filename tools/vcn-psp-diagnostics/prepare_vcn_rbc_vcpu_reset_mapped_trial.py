#!/usr/bin/env python3
"""Pulse VCPU_SOFT_RESET through the calibrated VCN ring-internal address.

The VCPU control packet at 0x1d8 was proven to toggle CLK_EN.  This trial
uses the corresponding VCN 2.0 internal reset offset (host 0x260 - 0x80)
to assert only VCPU reset, then release it in a second packet group.  Two
scratch writes calibrate execution; the outer runner cold-cycles afterward.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-vcpu-clock-mapped-20260929/vcn_v2_0.c'
SOURCE_SHA = '485e8e250c3a0c5c4adc47fc6fbed39a2c713ca877fc975358f83d1927fb1dac'
DEST = BUILD / 'vcn-rbc-vcpu-reset-mapped-20260929'
PACKET = 'PACKET0(mmUVD_VCPU_CNTL - 0x80, 0)'
RESET_PACKET = 'PACKET0(mmUVD_SOFT_RESET - 0x80, 0)'
OLD_FIRST = '0x0ff20200 & ~UVD_VCPU_CNTL__CLK_EN_MASK'
FIRST = 'UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK'
SECOND = '''\t\tWRITE_ONCE(ring->ring[17], 0x0ff20200);'''
RESET_SECOND = '''\t\tWRITE_ONCE(ring->ring[17], 0);'''
AFTER_SECOND = '''\t\tif (RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != 0x0ff20200) {'''
SAMPLE = '''\t\t{
\t\t\tu32 first = RREG32_SOC15(UVD, 0, mmUVD_STATUS);
\t\t\tu32 last = first, status_and = first, status_or = first;
\t\t\tu32 changes = 0;

\t\t\tfor (sample_i = 0; sample_i < 4096; ++sample_i) {
\t\t\t\tu32 status = RREG32_SOC15(UVD, 0, mmUVD_STATUS);

\t\t\t\tchanges += status != last;
\t\t\t\tstatus_and &= status;
\t\t\t\tstatus_or |= status;
\t\t\t\tlast = status;
\t\t\t\tudelay(5);
\t\t\t}
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN RBC VCPU mapped reset sample: first=%08x last=%08x and=%08x or=%08x changes=%u prid=%08x pc=%08x reset=%08x pf=%08x\\n",
\t\t\t\t first, last, status_and, status_or, changes,
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS));
\t\t}

'''


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned mapped VCPU clock source changed')
    source = data.decode()
    for old, count in ((PACKET, 2), (OLD_FIRST, 1), (SECOND, 1),
                       (AFTER_SECOND, 1)):
        if source.count(old) != count:
            raise ValueError(f'mapped reset anchor changed: {old[:50]}')
    source = source.replace(PACKET, RESET_PACKET)
    source = source.replace(OLD_FIRST, FIRST, 1)
    source = source.replace(SECOND, RESET_SECOND, 1)
    source = source.replace(AFTER_SECOND, SAMPLE + AFTER_SECOND, 1)
    source = source.replace('BC250 VCN RBC VCPU mapped clock ',
                            'BC250 VCN RBC VCPU mapped reset ')
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
