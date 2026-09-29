#!/usr/bin/env python3
"""Add a guarded PSP reset sample before the first VCPU retry write."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-dpg-bank-survey-20260929/vcn_v2_0.c'
DEST = BUILD / 'vcn-delayed-reset-20260929/vcn_v2_0.c'
SOURCE_SHA = '8eaf8de46c54b76f33aacd41906a3b3099492b286e2b146d06d072bf1fa7564b'
ANCHOR = '''\t\tif (adev->pdev->device == 0x13fe && i == 0)
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN VCPU wait0: pc=%08x pf=%08x latency=%08x\\n",
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CNTR));
\t\tr = 0;
'''

PROBE = '''\t\t/* The first powered PSP request already loaded the VCN firmware,
\t\t * mapped its cache windows and wrote reset=0. Sample only after a
\t\t * full wait, before Linux's first retry touches SOFT_RESET again.
\t\t * The RAM-only PSP hook recognizes this one scratch marker and
\t\t * reads reset before the signed driver's own control write.
\t\t */
\t\tif (adev->pdev->device == 0x13fe && i == 0 && !(status & 2)) {
\t\t\tstruct amdgpu_firmware_info *ucode =
\t\t\t\t&adev->firmware.ucode[AMDGPU_UCODE_ID_VCN];
\t\t\tu32 scratch_before, diag_status, scratch_after;
\t\t\tint diag_ret;

\t\t\tif (RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS) != 0x800 ||
\t\t\t    RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS) != 0 ||
\t\t\t    RREG32_SOC15(UVD, 0, mmUVD_VERSION) != 0x2001b)
\t\t\t\treturn -EINVAL;
\t\t\tscratch_before = RREG32(0x1f854 / 4);
\t\t\tif (scratch_before != 0)
\t\t\t\treturn -EINVAL;
\t\t\tWREG32(0x1f854 / 4, 0x5a13c0df);
\t\t\tif (RREG32(0x1f854 / 4) != 0x5a13c0df) {
\t\t\t\tWREG32(0x1f854 / 4, scratch_before);
\t\t\t\treturn -EIO;
\t\t\t}
\t\t\tdiag_ret = psp_execute_ip_fw_load(&adev->psp, ucode);
\t\t\tdiag_status = adev->psp.cmd_buf_mem->resp.status;
\t\t\tWREG32(0x1f854 / 4, scratch_before);
\t\t\tscratch_after = RREG32(0x1f854 / 4);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN delayed reset: ret=%d psp=%08x low28=%08x scratch=%08x status=%08x\\n",
\t\t\t\t diag_ret, diag_status, diag_status & 0x0fffffff,
\t\t\t\t scratch_after, status);
\t\t\tif (scratch_after != scratch_before ||
\t\t\t    (diag_status & 0xf0000000) != 0x70000000)
\t\t\t\treturn -EIO;
\t\t\treturn -ETIMEDOUT;
\t\t}
\t\tr = 0;
'''


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned VCN source changed')
    source = data.decode()
    if source.count(ANCHOR) != 1:
        raise ValueError('VCPU wait anchor changed')
    candidate = source.replace(ANCHOR, ANCHOR[:-len('\t\tr = 0;\n')] + PROBE, 1)
    if candidate.count('psp_execute_ip_fw_load(&adev->psp, ucode)') != 2:
        raise AssertionError('unexpected PSP request count')
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(candidate)
    print(DEST)
    print(hashlib.sha256(candidate.encode()).hexdigest())


if __name__ == '__main__':
    main()
