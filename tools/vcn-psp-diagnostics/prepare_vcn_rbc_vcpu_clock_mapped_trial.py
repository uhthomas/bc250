#!/usr/bin/env python3
"""Calibrate VCPU_CNTL packets at the VCN 2.0 ring-internal offset 0x1d8.

The in-tree driver maps several host segment-1 offsets to ring addresses by
subtracting 0x80 (GPCOM DATA0 0x584 -> 0x504, NO_OP 0x5bf -> 0x53f).
VCPU_CNTL is host offset 0x258, so this tests 0x1d8 with the existing
two-stage clock toggle, scratch markers, and host restore fallback.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-vcpu-clock-internal-20260929/vcn_v2_0.c'
SOURCE_SHA = 'd0e3acd3824fac1cd26ca040d173e3ef2f71849ee6fc167bc03decca14aff7de'
DEST = BUILD / 'vcn-rbc-vcpu-clock-mapped-20260929'
OLD = 'PACKET0(mmUVD_VCPU_CNTL, 0)'
NEW = 'PACKET0(mmUVD_VCPU_CNTL - 0x80, 0)'


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned ring VCPU clock source changed')
    source = data.decode()
    if source.count(OLD) != 2:
        raise ValueError('VCPU control packet anchors changed')
    source = source.replace(OLD, NEW)
    source = source.replace('BC250 VCN RBC VCPU internal clock ',
                            'BC250 VCN RBC VCPU mapped clock ')
    vcn = BUILD / 'vcn-rbc-vcpu-clock-internal-20260929/amdgpu_vcn.c'
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
