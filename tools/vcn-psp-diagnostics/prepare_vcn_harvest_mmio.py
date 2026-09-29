#!/usr/bin/env python3
"""Add one guarded host-MMIO harvest read to the pinned VCN diagnostic.

This creates a separate, default-off kernel source in ignored output/. It
does not modify the installed image or any firmware.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-postrelease-measure-20260927/vcn_v2_0.c'
DEST = BUILD / 'vcn-harvest-mmio-20260928/vcn_v2_0.c'
SOURCE_SHA = 'ea5cecf60b5c0e251d2d1f5ba5064fed6b8811da2eb7bb7ec6b674eab8b2c590'
ANCHOR = '''\tif (adev->pdev->device == 0x13fe) {
\t\tstruct amdgpu_firmware_info *ucode =
\t\t\t&adev->firmware.ucode[AMDGPU_UCODE_ID_VCN];
\t\tint postrelease_ret;
'''
PROBE = '''\t/* Read the actual PCI BAR VCN register only after the adjacent power
\t * and PGFSM registers have responded in this known diagnostic state.
\t * A recovery entry is staged by the runner before module insertion.
\t */
\tif (adev->pdev->device == 0x13fe) {
\t\tu32 power = RREG32_SOC15(VCN, 0, mmUVD_POWER_STATUS);
\t\tu32 pgfsm = RREG32_SOC15(VCN, 0, mmUVD_PGFSM_STATUS);

\t\tif (power == 0x800 && pgfsm == 0)
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN harvest MMIO: power=%08x pgfsm=%08x harvest=%08x\\n",
\t\t\t\t power, pgfsm,
\t\t\t\t RREG32_SOC15(VCN, 0, mmCC_UVD_HARVESTING));
\t\telse
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN harvest MMIO skipped: power=%08x pgfsm=%08x\\n",
\t\t\t\t power, pgfsm);
\t}

'''


def main():
    data = SOURCE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA
    source = data.decode()
    assert source.count(ANCHOR) == 1
    source = source.replace(ANCHOR, PROBE + ANCHOR, 1)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST)
    print(hashlib.sha256(source.encode()).hexdigest())


if __name__ == '__main__':
    main()
