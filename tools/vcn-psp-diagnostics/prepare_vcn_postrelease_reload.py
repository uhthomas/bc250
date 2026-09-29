#!/usr/bin/env python3
"""Retry the guarded PSP map/reset service after host VCPU release writes."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-map-exec-trace-20260927/vcn_v2_0.c'
DEST = BUILD / 'vcn-postrelease-reload-20260927/vcn_v2_0.c'
SOURCE_SHA = '25bb6dad73dfaa9d8aeff0cea3486a4f66b7a7bd2c939bd0632f58fb68102378'
ANCHOR = '\tif (adev->pdev->device == 0x13fe)\n\t\tdev_warn(adev->dev,\n\t\t\t "BC250 VCN VCPU release:'
RELOAD = '''\tif (adev->pdev->device == 0x13fe) {
\t\tstruct amdgpu_firmware_info *ucode =
\t\t\t&adev->firmware.ucode[AMDGPU_UCODE_ID_VCN];
\t\tint postrelease_ret;

\t\t/* The guarded first request matched all live GPU allocations.
\t\t * Reapply the same PSP map and reset release only after the host's
\t\t * read-modify-write sequence has completed.
\t\t */
\t\tpostrelease_ret = psp_execute_ip_fw_load(&adev->psp, ucode);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN postrelease reload: ret=%d psp_status=%08x status=%08x\\n",
\t\t\t postrelease_ret, adev->psp.cmd_buf_mem->resp.status,
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS));
\t\tif (postrelease_ret || adev->psp.cmd_buf_mem->resp.status)
\t\t\treturn postrelease_ret ? postrelease_ret : -EIO;
\t}

'''


def main():
    data = SOURCE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA
    source = data.decode()
    assert source.count(ANCHOR) == 1
    source = source.replace(ANCHOR, RELOAD + ANCHOR, 1)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST)
    print(hashlib.sha256(source.encode()).hexdigest())


if __name__ == '__main__':
    main()
