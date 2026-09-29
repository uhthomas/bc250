#!/usr/bin/env python3
"""Repeat the reversible VCPU clock calibration with ring address 0x0258.

The 0xc258 form executed surrounding SCRATCH9 packets but did not change
the documented CLK_EN bit. This changes only the two VCPU_CNTL packet
addresses, retaining both marker controls and the host restore fallback.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-vcpu-clock-20260929/vcn_v2_0.c'
SOURCE_SHA = 'ca0152ac6bc82fe427e2e798fa3baff5257039c581cc82f8297bb318ac9a6317'
DEST = BUILD / 'vcn-rbc-vcpu-clock-internal-20260929'
OLD = 'PACKET0(0xc000 | mmUVD_VCPU_CNTL, 0)'
NEW = 'PACKET0(mmUVD_VCPU_CNTL, 0)'


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned RBC VCPU clock source changed')
    source = data.decode()
    if source.count(OLD) != 2:
        raise ValueError('VCPU control packet anchors changed')
    source = source.replace(OLD, NEW)
    source = source.replace('BC250 VCN RBC VCPU clock ',
                            'BC250 VCN RBC VCPU internal clock ')
    DEST.mkdir(parents=True, exist_ok=True)
    vcn = BUILD / 'vcn-rbc-vcpu-clock-20260929/amdgpu_vcn.c'
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
