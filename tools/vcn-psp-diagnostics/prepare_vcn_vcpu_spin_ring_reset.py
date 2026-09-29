#!/usr/bin/env python3
"""Combine the direct-BO Xtensa spin canary with calibrated RBC VCPU reset.

The VCPU BO contains the three-byte self-loop. A separate ring packet asserts
and releases VCPU reset, then samples PC/PRID/status. The candidate is limited
to the opt-in module and is cold-cycled after one trial.
"""

import hashlib
from pathlib import Path

import prepare_vcn_direct_bo_powered as direct


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
VCN = BUILD / 'vcn-vcpu-spin-stub-20260929/amdgpu_vcn.c'
VCN_SHA = 'b96c3f99ecd10ee607b256a2b0608bd10dacbc4f008f9f4820c8a8c9616963ef'
SOURCE = BUILD / 'vcn-rbc-vcpu-reset-mapped-20260929/vcn_v2_0.c'
SOURCE_SHA = 'e5fde867ccd88198b7f403172788c11859610111d9b5d1a46fc65bf2abb57314'
DEST = BUILD / 'vcn-vcpu-spin-ring-reset-20260929'


def main() -> None:
    vcn = VCN.read_bytes()
    source = SOURCE.read_bytes()
    if (hashlib.sha256(vcn).hexdigest() != VCN_SHA or
            hashlib.sha256(source).hexdigest() != SOURCE_SHA):
        raise ValueError('pinned direct-BO or RBC reset source changed')
    body = source.decode()
    if (body.count(direct.PSP_BLOCK_START) != 1 or
            body.count(direct.PSP_BLOCK_END) != 1 or
            body.count('BC250 VCN RBC VCPU mapped reset sample:') != 1):
        raise ValueError('VCN reset probe or PSP block boundary changed')
    start = body.index(direct.PSP_BLOCK_START)
    end = body.index(direct.PSP_BLOCK_END, start)
    body = body[:start] + direct.DIRECT_BLOCK + body[end:]
    if ('BC250 VCN direct BO:' not in body or
            'BC250 VCN RBC VCPU mapped reset sample:' not in body or
            'BC250 VCN postpower reload:' in body):
        raise AssertionError('direct-BO reset probe composition failed')
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in (('amdgpu_vcn.c', vcn), ('vcn_v2_0.c', body.encode())):
        path = DEST / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_bytes(data)
        print(name, hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    main()
