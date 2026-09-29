#!/usr/bin/env python3
"""Stage a BC250-only volatile host/PSP VCN scratch visibility control."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-postrelease-measure-20260927/vcn_v2_0.c'
DEST = BUILD / 'vcn-crosspath-scratch-20260929/vcn_v2_0.c'
SOURCE_SHA = 'ea5cecf60b5c0e251d2d1f5ba5064fed6b8811da2eb7bb7ec6b674eab8b2c590'
ANCHOR = '''\t\tdev_warn(adev->dev, "BC250 VCN postrelease allocation matched\\n");
\t\t/* The guarded first request matched all live GPU allocations.
\t\t * Reapply the same PSP map and reset release only after the host's
\t\t * read-modify-write sequence has completed.
\t\t */
\t\tpostrelease_ret = psp_execute_ip_fw_load(&adev->psp, ucode);
'''
PROBE = '''\t\t/* A VCN-owned scratch word beside the harvest/power registers
\t\t * compares the host BAR and PSP SVC route at one instant.
\t\t * Abort if the original or readback differs from the pinned trial.
\t\t * The PSP hook only reads this address; restore it even on failure.
\t\t */
\t\t{
\t\t\tu32 scratch_before, scratch_during, scratch_after;
\t\t\tu32 scratch_soc15;

\t\t\t/* The PSP argument is the absolute 0x1f854 BAR byte offset.
\t\t\t * The adjacent JPEG block is not enabled in this VCN-only probe.
\t\t\t */
\t\t\tscratch_soc15 = RREG32_SOC15(VCN, 0, mmUVD_SCRATCH1);
\t\t\tscratch_before = RREG32(0x1f854 / 4);
\t\t\tdev_warn(adev->dev, "BC250 VCN scratch routes: soc15=%08x bar=%08x\\n",
\t\t\t\t scratch_soc15, scratch_before);
\t\t\tif (scratch_before != 0) {
\t\t\t\tdev_err(adev->dev, "BC250 VCN scratch baseline differs: %08x\\n",
\t\t\t\t\t scratch_before);
\t\t\t\treturn -EINVAL;
\t\t\t}
\t\t\tWREG32(0x1f854 / 4, 0x5a13c0de);
\t\t\tscratch_during = RREG32(0x1f854 / 4);
\t\t\tdev_warn(adev->dev, "BC250 VCN scratch before PSP: %08x/%08x\\n",
\t\t\t\t scratch_before, scratch_during);
\t\t\tif (scratch_during != 0x5a13c0de) {
\t\t\t\tWREG32(0x1f854 / 4, scratch_before);
\t\t\t\treturn -EIO;
\t\t\t}
\t\t\tpostrelease_ret = psp_execute_ip_fw_load(&adev->psp, ucode);
\t\t\tWREG32(0x1f854 / 4, scratch_before);
\t\t\tscratch_after = RREG32(0x1f854 / 4);
\t\t\tdev_warn(adev->dev, "BC250 VCN scratch after PSP: %08x\\n",
\t\t\t\t scratch_after);
\t\t\tif (scratch_after != scratch_before)
\t\t\t\treturn -EIO;
\t\t}
'''


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned postrelease source changed')
    source = data.decode()
    if source.count(ANCHOR) != 1:
        raise ValueError('postrelease PSP call site changed')
    source = source.replace(ANCHOR, ANCHOR.replace(
        '\t\tpostrelease_ret = psp_execute_ip_fw_load(&adev->psp, ucode);\n',
        PROBE), 1)
    if source.count('psp_execute_ip_fw_load(&adev->psp, ucode)') != 1:
        raise ValueError('PSP request count changed')
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST)
    print(hashlib.sha256(source.encode()).hexdigest())


if __name__ == '__main__':
    main()
