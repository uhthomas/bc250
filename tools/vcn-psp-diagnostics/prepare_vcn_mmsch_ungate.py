#!/usr/bin/env python3
"""Test both MMSCH software clock mode and gate during guarded VCPU startup."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-tmr-bar-oracle-20260929/vcn_v2_0.c'
SOURCE_SHA = '0d49825d10f006696f45c16ea09b2009e68852e3b17af00cacb890f4f101d5da'
VCN = BUILD / 'vcn-rbc-tmr-bar-oracle-20260929/amdgpu_vcn.c'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'
DEST = BUILD / 'vcn-mmsch-ungate-20260929'

RESET_OLD = '''\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET,
\t\t\t\t UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\tudelay(10);
\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET, 0);'''
RESET_NEW = '''\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET,
\t\t\t\t UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\t/* VCN 2.0 static path leaves MMSCH_MODE and MMSCH gate set.
\t\t * Temporarily clear only those bits, then restore after wait0.
\t\t */
\t\t{
\t\t\tu32 ctrl = RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL);
\t\t\tu32 gate = RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE);
\t\t\tu32 reset2 = RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET2);

\t\t\tif (ctrl != 0x8000018c || gate != 0x00100000 ||
\t\t\t    RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS) != 0x800 ||
\t\t\t    RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS) != 0 ||
\t\t\t    RREG32_SOC15(UVD, 0, mmCC_UVD_HARVESTING) != 3)
\t\t\t\treturn -EINVAL;
\t\t\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_CGC_CTRL),
\t\t\t\t0, ~UVD_CGC_CTRL__MMSCH_MODE_MASK);
\t\t\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_CGC_GATE),
\t\t\t\t0, ~UVD_CGC_GATE__MMSCH_MASK);
\t\t\tudelay(100);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 MMSCH ungate held: ctrl0=%08x gate0=%08x reset20=%08x ctrl=%08x gate=%08x reset2=%08x cgc=%08x status=%08x\\n",
\t\t\t\t ctrl, gate, reset2,
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET2),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS));
\t\t\tif (RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL) !=
\t\t\t    (ctrl & ~UVD_CGC_CTRL__MMSCH_MODE_MASK) ||
\t\t\t    RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE) !=
\t\t\t    (gate & ~UVD_CGC_GATE__MMSCH_MASK)) {
\t\t\t\tWREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL, ctrl);
\t\t\t\tWREG32_SOC15(UVD, 0, mmUVD_CGC_GATE, gate);
\t\t\t\treturn -EIO;
\t\t\t}
\t\t}
\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET, 0);
\t\tudelay(100);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 MMSCH ungate released: ctrl=%08x gate=%08x reset2=%08x cgc=%08x status=%08x pc=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET2),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE));'''

WAIT_OLD = '''\t\tif (adev->pdev->device == 0x13fe && i == 0)
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN LMI wait0: lmi=%08x ctrl=%08x ctrl2=%08x vcpu=%08x\\n",'''
WAIT_NEW = '''\t\tif (adev->pdev->device == 0x13fe && i == 0) {
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 MMSCH ungate wait0: ctrl=%08x gate=%08x reset2=%08x cgc=%08x status=%08x pc=%08x\\n",
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET2),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE));
\t\t\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_CGC_GATE),
\t\t\t\tUVD_CGC_GATE__MMSCH_MASK,
\t\t\t\t~UVD_CGC_GATE__MMSCH_MASK);
\t\t\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_CGC_CTRL),
\t\t\t\tUVD_CGC_CTRL__MMSCH_MODE_MASK,
\t\t\t\t~UVD_CGC_CTRL__MMSCH_MODE_MASK);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 MMSCH ungate restored: ctrl=%08x gate=%08x reset2=%08x\\n",
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET2));
\t\t}
\t\tif (adev->pdev->device == 0x13fe && i == 0)
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN LMI wait0: lmi=%08x ctrl=%08x ctrl2=%08x vcpu=%08x\\n",'''


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'MMSCH ungate anchor changed: {old[:70]!r}')
    return source.replace(old, new, 1)


def main() -> None:
    source = SOURCE.read_bytes()
    vcn = VCN.read_bytes()
    if (hashlib.sha256(source).hexdigest() != SOURCE_SHA or
            hashlib.sha256(vcn).hexdigest() != VCN_SHA):
        raise ValueError('pinned TMR BAR oracle source changed')
    candidate = replace_once(source.decode(), RESET_OLD, RESET_NEW)
    candidate = replace_once(candidate, WAIT_OLD, WAIT_NEW)
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in (('vcn_v2_0.c', candidate.encode()),
                       ('amdgpu_vcn.c', vcn)):
        path = DEST / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_bytes(data)
        print(name, hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    main()
