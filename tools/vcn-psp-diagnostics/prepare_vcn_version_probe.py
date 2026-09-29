#!/usr/bin/env python3
"""Add read-only VCN-version samples to the proven PSP-load startup trial."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "output/video-decode-20260922/kernel-build"
SOURCE = BUILD / "vcn-map-exec-trace-20260927/vcn_v2_0.c"
DEST = BUILD / "vcn-version-probe-20260928/vcn_v2_0.c"
SOURCE_SHA = "25bb6dad73dfaa9d8aeff0cea3486a4f66b7a7bd2c939bd0632f58fb68102378"

PRE_ANCHOR = "\tif (adev->pm.dpm_enabled)\n\t\tamdgpu_dpm_enable_vcn(adev, true, 0);\n"
POWER_ANCHOR = "\tvcn_v2_0_mc_resume(vinst);\n"
RELEASE_ANCHOR = ("\t/* release VCPU reset to boot */\n"
                  "\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_SOFT_RESET), 0,\n")
AFTER_ANCHOR = "\tWREG32_SOC15(UVD, 0, mmUVD_LMI_SWAP_CNTL, lmi_swap_cntl);\n"

PRE = '''\t/* The existing trace already reads status/power at this state. */
\tif (adev->pdev->device == 0x13fe) {
\t\tu32 power = RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS);
\t\tu32 pgfsm = RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS);

\t\tif (power == 0x801 && pgfsm == 0x00200000)
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN version pre: power=%08x pgfsm=%08x version=%08x\\n",
\t\t\t\t power, pgfsm, RREG32_SOC15(UVD, 0, mmUVD_VERSION));
\t\telse
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN version pre skipped: power=%08x pgfsm=%08x\\n",
\t\t\t\t power, pgfsm);
\t}

'''

POWER = '''\t/* Read only when the known powered state is present. These reads
\t * distinguish an exposed VCN register file from the status stub.
\t */
\tif (adev->pdev->device == 0x13fe) {
\t\tu32 power = RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS);
\t\tu32 pgfsm = RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS);

\t\tif (power == 0x800 && pgfsm == 0)
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN version powered: power=%08x pgfsm=%08x version=%08x harvest=%08x\\n",
\t\t\t\t power, pgfsm,
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VERSION),
\t\t\t\t RREG32_SOC15(UVD, 0, mmCC_UVD_HARVESTING));
\t\telse
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN version powered skipped: power=%08x pgfsm=%08x\\n",
\t\t\t\t power, pgfsm);
\t}

'''

RELEASE = '''\tif (adev->pdev->device == 0x13fe) {
\t\tu32 power = RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS);
\t\tu32 pgfsm = RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS);

\t\tif (power == 0x800 && pgfsm == 0)
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN version before release: version=%08x harvest=%08x\\n",
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VERSION),
\t\t\t\t RREG32_SOC15(UVD, 0, mmCC_UVD_HARVESTING));
\t}

'''

AFTER = '''\tif (adev->pdev->device == 0x13fe) {
\t\tu32 power = RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS);
\t\tu32 pgfsm = RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS);

\t\tif (power == 0x800 && pgfsm == 0)
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN version after release: version=%08x harvest=%08x status=%08x\\n",
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VERSION),
\t\t\t\t RREG32_SOC15(UVD, 0, mmCC_UVD_HARVESTING),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS));
\t}

'''


def main():
    source_bytes = SOURCE.read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest() == SOURCE_SHA
    source = source_bytes.decode()
    for anchor, addition in (
        (PRE_ANCHOR, PRE),
        (POWER_ANCHOR, POWER),
        (RELEASE_ANCHOR, RELEASE),
        (AFTER_ANCHOR, AFTER),
    ):
        assert source.count(anchor) == 1, anchor
        source = source.replace(anchor, addition + anchor, 1)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST)
    print(hashlib.sha256(source.encode()).hexdigest())


if __name__ == "__main__":
    main()
