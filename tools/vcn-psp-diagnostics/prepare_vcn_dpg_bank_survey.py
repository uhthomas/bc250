#!/usr/bin/env python3
"""Add a read-only DPG VCPU-cache-bank survey to the guarded VCN control."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-crosspath-scratch-20260929/vcn_v2_0.c'
DEST = BUILD / 'vcn-dpg-bank-survey-20260929/vcn_v2_0.c'
SOURCE_SHA = '842af465e35c7ee9537f17800ee62183ef6d3e55fe52c5bb7743c51eee136be8'
PRE_ANCHOR = '\t\tdev_warn(adev->dev, "BC250 VCN postrelease allocation matched\\n");\n'
POST_ANCHOR = '''\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN postrelease reload: ret=%d psp_status=%08x status=%08x\\n",'''


def sample(phase: str) -> str:
    return f'''\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN DPG bank {phase}: low=%08x high=%08x off0=%08x vmid=%08x report=%08x rawlow=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_DPG_LMI_VCPU_CACHE_64BIT_BAR_LOW),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_DPG_LMI_VCPU_CACHE_64BIT_BAR_HIGH),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_DPG_VCPU_CACHE_OFFSET0),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_DPG_LMI_VCPU_CACHE_VMID),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_DPG_CLK_EN_VCPU_REPORT),
\t\t\t RREG32(0x1f894 / 4));
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN standard bank {phase}: low=%08x reset=%08x reset2=%08x vcpu=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_VCPU_CACHE_64BIT_BAR_LOW),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET2),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL));
'''


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned scratch-control source changed')
    source = data.decode()
    if source.count(PRE_ANCHOR) != 1 or source.count(POST_ANCHOR) != 1:
        raise ValueError('guarded PSP call site changed')
    before = '''\t\t/* Read-only comparison of the alternate VCPU cache bank.
\t\t * The known-live scratch word and PSP read still guard this phase.
\t\t */
\t\tif (RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS) != 0x800 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS) != 0 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_VERSION) != 0x2001b) {
\t\t\tdev_err(adev->dev, "BC250 VCN DPG survey power guard failed\\n");
\t\t\treturn -EINVAL;
\t\t}
'''
    source = source.replace(PRE_ANCHOR, PRE_ANCHOR + before + sample('pre'), 1)
    source = source.replace(POST_ANCHOR, sample('post') + POST_ANCHOR, 1)
    if source.count('psp_execute_ip_fw_load(&adev->psp, ucode)') != 1:
        raise ValueError('PSP request count changed')
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST)
    print(hashlib.sha256(source.encode()).hexdigest())


if __name__ == '__main__':
    main()
