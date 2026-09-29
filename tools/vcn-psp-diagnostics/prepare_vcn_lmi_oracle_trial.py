#!/usr/bin/env python3
"""Try one guarded PS5-style LMI control setting before VCN VCPU release.

The PS5 manufacturing-driver decompile suggests this value; the experiment
does not assume that decompile is correct or that PS5 firmware matches ours.
It changes one volatile register on the diagnostic kernel path only.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "output/video-decode-20260922/kernel-build"
SOURCE = BUILD / "vcn-version-probe-20260928/vcn_v2_0.c"
DEST = BUILD / "vcn-lmi-oracle-20260928/vcn_v2_0.c"
SOURCE_SHA = "8f1ab1da21fa3193b115e77a3ca7539f175c98af78e29fcbfeae39d87e73d120"

ANCHOR = ("\t/* release VCPU reset to boot */\n"
          "\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_SOFT_RESET), 0,\n")
PROBE = '''\t/* BC250 diagnostic only: the archived PS5 manufacturing path uses
\t * (old & 0xffdfdc00) | 0x00202108 for LMI_CTRL before VCPU release.
\t * Guard the exact powered/VCPU state. A failed readback restores the
\t * original register word before normal startup continues.
\t */
\tif (adev->pdev->device == 0x13fe) {
\t\tu32 power = RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS);
\t\tu32 pgfsm = RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS);
\t\tu32 version = RREG32_SOC15(UVD, 0, mmUVD_VERSION);
\t\tu32 harvest = RREG32_SOC15(UVD, 0, mmCC_UVD_HARVESTING);
\t\tu32 vcpu = RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL);
\t\tu32 before = RREG32_SOC15(UVD, 0, mmUVD_LMI_CTRL);

\t\tif (power == 0x800 && pgfsm == 0 && version == 0x0002001b &&
\t\t    harvest == 3 && vcpu == 0x0ff20200 &&
\t\t    before != 0xffffffff &&
\t\t    (before & 0x00203100) == 0x00203100) {
\t\t\tu32 candidate = (before & 0xffdfdc00) | 0x00202108;
\t\t\tu32 observed = before;

\t\t\tif (candidate != before) {
\t\t\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_CTRL, candidate);
\t\t\t\tobserved = RREG32_SOC15(UVD, 0, mmUVD_LMI_CTRL);
\t\t\t\tif (observed != candidate)
\t\t\t\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_CTRL, before);
\t\t\t}
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN VCPU LMI oracle: before=%08x candidate=%08x observed=%08x applied=%u\\n",
\t\t\t\t before, candidate, observed,
\t\t\t\t candidate != before && observed == candidate);
\t\t} else {
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN VCPU LMI oracle skipped: power=%08x pgfsm=%08x version=%08x harvest=%08x vcpu=%08x lmi=%08x\\n",
\t\t\t\t power, pgfsm, version, harvest, vcpu, before);
\t\t}
\t}

'''


def main():
    source_bytes = SOURCE.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != SOURCE_SHA:
        raise ValueError("pinned VCN source changed")
    source = source_bytes.decode()
    if source.count(ANCHOR) != 1:
        raise ValueError("expected one VCPU release anchor")
    candidate = source.replace(ANCHOR, PROBE + ANCHOR, 1)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(candidate)
    print(DEST)
    print(hashlib.sha256(candidate.encode()).hexdigest())


if __name__ == "__main__":
    main()
