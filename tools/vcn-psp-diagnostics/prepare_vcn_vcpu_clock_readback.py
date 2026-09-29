#!/usr/bin/env python3
"""Probe one VCPU clock-control bit before releasing the VCPU reset."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "output/video-decode-20260922/kernel-build"
SOURCE = BUILD / "vcn-version-probe-20260928/vcn_v2_0.c"
DEST = BUILD / "vcn-vcpu-clock-readback-20260928/vcn_v2_0.c"
SOURCE_SHA = "8f1ab1da21fa3193b115e77a3ca7539f175c98af78e29fcbfeae39d87e73d120"

ANCHOR = '''\tif (adev->pdev->device == 0x13fe) {
\t\tu32 power = RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS);
\t\tu32 pgfsm = RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS);

\t\tif (power == 0x800 && pgfsm == 0)
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN version before release: version=%08x harvest=%08x\\n",
'''

PROBE = '''\t/* VCPU is still held in reset here. Briefly clear only CLK_EN and
\t * restore the exact prior word before continuing ordinary startup.
\t */
\tif (adev->pdev->device == 0x13fe) {
\t\tu32 power = RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS);
\t\tu32 pgfsm = RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS);
\t\tu32 version = RREG32_SOC15(UVD, 0, mmUVD_VERSION);
\t\tu32 harvest = RREG32_SOC15(UVD, 0, mmCC_UVD_HARVESTING);
\t\tu32 before = RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL);

\t\tif (power == 0x800 && pgfsm == 0 && version == 0x0002001b &&
\t\t    harvest == 3 && before == 0x0ff20200) {
\t\t\tu32 cleared, restored;

\t\t\tWREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL,
\t\t\t\t       before & ~UVD_VCPU_CNTL__CLK_EN_MASK);
\t\t\tudelay(10);
\t\t\tcleared = RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL);
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL, before);
\t\t\trestored = RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN VCPU clock readback: before=%08x cleared=%08x restored=%08x\\n",
\t\t\t\t before, cleared, restored);
\t\t} else {
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN VCPU clock probe skipped: power=%08x pgfsm=%08x version=%08x harvest=%08x vcpu=%08x\\n",
\t\t\t\t power, pgfsm, version, harvest, before);
\t\t}
\t}

'''


def main():
    source_bytes = SOURCE.read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest() == SOURCE_SHA
    source = source_bytes.decode()
    assert source.count(ANCHOR) == 1
    source = source.replace(ANCHOR, PROBE + ANCHOR, 1)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST)
    print(hashlib.sha256(source.encode()).hexdigest())


if __name__ == "__main__":
    main()
