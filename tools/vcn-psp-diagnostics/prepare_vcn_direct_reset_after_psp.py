#!/usr/bin/env python3
"""Try direct VCPU/LMI reset writes after the pinned, successful PSP load."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "output/video-decode-20260922/kernel-build"
SOURCE = BUILD / "vcn-version-probe-20260928/vcn_v2_0.c"
DEST = BUILD / "vcn-direct-reset-after-psp-20260928/vcn_v2_0.c"
SOURCE_SHA = "8f1ab1da21fa3193b115e77a3ca7539f175c98af78e29fcbfeae39d87e73d120"

RELEASE_OLD = '''\t/* release VCPU reset to boot */
\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_SOFT_RESET), 0,
\t\t~UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
'''
RELEASE_NEW = '''\t/* On this BC250 UVD_SOFT_RESET reads as all ones. Avoid carrying
\t * those read bits into the reset write after the successful PSP load.
\t * The VCN 2.0 DPG startup path also writes this register directly.
\t */
\tif (adev->pdev->device == 0x13fe) {
\t\tu32 power = RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS);
\t\tu32 pgfsm = RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS);
\t\tu32 version = RREG32_SOC15(UVD, 0, mmUVD_VERSION);
\t\tu32 harvest = RREG32_SOC15(UVD, 0, mmCC_UVD_HARVESTING);

\t\tif (power != 0x800 || pgfsm || version != 0x0002001b ||
\t\t    harvest != 3) {
\t\t\tdev_err(adev->dev,
\t\t\t\t"BC250 VCN direct reset guard: power=%08x pgfsm=%08x version=%08x harvest=%08x\\n",
\t\t\t\tpower, pgfsm, version, harvest);
\t\t\treturn -EINVAL;
\t\t}
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN direct reset before: reset=%08x status=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS));
\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET,
\t\t\t\t UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\tudelay(10);
\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET, 0);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN direct reset released: reset=%08x status=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS));
\t} else {
\t\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_SOFT_RESET), 0,
\t\t\t~UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t}
'''

LMI_OLD = '''\ttmp = RREG32_SOC15(VCN, 0, mmUVD_SOFT_RESET);
\ttmp &= ~UVD_SOFT_RESET__LMI_SOFT_RESET_MASK;
\ttmp &= ~UVD_SOFT_RESET__LMI_UMC_SOFT_RESET_MASK;
\tWREG32_SOC15(VCN, 0, mmUVD_SOFT_RESET, tmp);
'''
LMI_NEW = '''\tif (adev->pdev->device == 0x13fe) {
\t\tWREG32_SOC15(VCN, 0, mmUVD_SOFT_RESET, 0);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN direct reset LMI released: reset=%08x status=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS));
\t} else {
\t\ttmp = RREG32_SOC15(VCN, 0, mmUVD_SOFT_RESET);
\t\ttmp &= ~UVD_SOFT_RESET__LMI_SOFT_RESET_MASK;
\t\ttmp &= ~UVD_SOFT_RESET__LMI_UMC_SOFT_RESET_MASK;
\t\tWREG32_SOC15(VCN, 0, mmUVD_SOFT_RESET, tmp);
\t}
'''

RETRY_OLD = '''\t\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_SOFT_RESET),
\t\t\tUVD_SOFT_RESET__VCPU_SOFT_RESET_MASK,
\t\t\t~UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\tmdelay(10);
\t\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_SOFT_RESET), 0,
\t\t\t~UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
'''
RETRY_NEW = '''\t\tif (adev->pdev->device == 0x13fe)
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET,
\t\t\t\t\t UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\telse
\t\t\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_SOFT_RESET),
\t\t\t\tUVD_SOFT_RESET__VCPU_SOFT_RESET_MASK,
\t\t\t\t~UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\tmdelay(10);
\t\tif (adev->pdev->device == 0x13fe)
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET, 0);
\t\telse
\t\t\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_SOFT_RESET), 0,
\t\t\t\t~UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
'''


def main():
    source_bytes = SOURCE.read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest() == SOURCE_SHA
    source = source_bytes.decode()
    for old, new in ((RELEASE_OLD, RELEASE_NEW),
                     (LMI_OLD, LMI_NEW),
                     (RETRY_OLD, RETRY_NEW)):
        assert source.count(old) == 1, old
        source = source.replace(old, new, 1)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST)
    print(hashlib.sha256(source.encode()).hexdigest())


if __name__ == "__main__":
    main()
