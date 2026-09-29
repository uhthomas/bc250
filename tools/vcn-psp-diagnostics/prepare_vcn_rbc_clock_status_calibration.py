#!/usr/bin/env python3
"""Check whether CGC_STATUS follows a known working RBC clock gate.

The ring is idle and VCPU reset is held during this volatile differential.
The RBC gate is restored before the existing signed TMR BAR ring oracle runs.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-tmr-bar-oracle-20260929/vcn_v2_0.c'
SOURCE_SHA = '0d49825d10f006696f45c16ea09b2009e68852e3b17af00cacb890f4f101d5da'
VCN = BUILD / 'vcn-rbc-tmr-bar-oracle-20260929/amdgpu_vcn.c'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'
DEST = BUILD / 'vcn-rbc-clock-status-calibration-20260929'

OLD = '''\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET,
\t\t\t\t UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\tudelay(10);
\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET, 0);'''
NEW = '''\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET,
\t\t\t\t UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\t/* Calibrate CGC_STATUS against the RBC that later fetches the
\t\t * signed oracle packets. No ring packet runs while gated.
\t\t */
\t\t{
\t\t\tu32 gate0 = RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE);
\t\t\tu32 ctrl = RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL);
\t\t\tu32 status0 = RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS);
\t\t\tu32 gate1, status1, gate2, status2;

\t\t\tif (gate0 != 0x00100000 || ctrl != 0x8000018c ||
\t\t\t    status0 != 0xbfffffff ||
\t\t\t    RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != 0x0ff20200)
\t\t\t\treturn -EINVAL;
\t\t\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_CGC_GATE),
\t\t\t\tUVD_CGC_GATE__RBC_MASK,
\t\t\t\t~UVD_CGC_GATE__RBC_MASK);
\t\t\tudelay(100);
\t\t\tgate1 = RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE);
\t\t\tstatus1 = RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS);
\t\t\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_CGC_GATE),
\t\t\t\t0, ~UVD_CGC_GATE__RBC_MASK);
\t\t\tudelay(100);
\t\t\tgate2 = RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE);
\t\t\tstatus2 = RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 RBC clock status calibration: gate0=%08x gate1=%08x gate2=%08x status0=%08x status1=%08x status2=%08x ctrl=%08x\\n",
\t\t\t\t gate0, gate1, gate2, status0, status1,
\t\t\t\t status2, ctrl);
\t\t\tif (gate1 != (gate0 | UVD_CGC_GATE__RBC_MASK) ||
\t\t\t    gate2 != gate0)
\t\t\t\treturn -EIO;
\t\t}
\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET, 0);'''


def main() -> None:
    source = SOURCE.read_bytes()
    vcn = VCN.read_bytes()
    if (hashlib.sha256(source).hexdigest() != SOURCE_SHA or
            hashlib.sha256(vcn).hexdigest() != VCN_SHA):
        raise ValueError('pinned TMR BAR oracle source changed')
    decoded = source.decode()
    if decoded.count(OLD) != 1:
        raise ValueError('RBC clock gate insertion point changed')
    candidate = decoded.replace(OLD, NEW, 1).encode()
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in (('vcn_v2_0.c', candidate), ('amdgpu_vcn.c', vcn)):
        path = DEST / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_bytes(data)
        print(name, hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    main()
