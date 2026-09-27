#!/usr/bin/env python3
"""Prepare a one-shot VCN firmware reload immediately after PGFSM power-up.

The original PSP load occurs before vcn_v2_0_start(). This experiment repeats
that same volatile PSP request after the host observes all VCN tiles powered,
then compares register access before proceeding to the VCPU startup path.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-uvdw-power-20260927/vcn_v2_0.c'
DEST = BUILD / 'vcn-postpower-reload-20260927/vcn_v2_0.c'
SOURCE_SHA = '6703cc0900b1e2be5c2d604951d119b0b277b272ff5564626d1ef3893ead863d'

BEFORE = '\tvcn_v2_0_disable_static_power_gating(vinst);\n\n\t/* set uvd status busy */'
AFTER = '''\tvcn_v2_0_disable_static_power_gating(vinst);

\tif (adev->pdev->device == 0x13fe) {
\t\tstruct amdgpu_firmware_info *ucode =
\t\t\t&adev->firmware.ucode[AMDGPU_UCODE_ID_VCN];
\t\tu32 old_lo = ucode->tmr_mc_addr_lo;
\t\tu32 old_hi = ucode->tmr_mc_addr_hi;
\t\tint reload_ret;

\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN postpower pre: pgfsm=%08x power=%08x status=%08x reset=%08x cache=%08x staged=%llx fw=%08x%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_VCPU_CACHE_64BIT_BAR_LOW),
\t\t\t (unsigned long long)ucode->mc_addr, old_hi, old_lo);
\t\tif (!ucode->fw || !ucode->ucode_size || !ucode->mc_addr ||
\t\t    (old_hi == 0 && old_lo == 0)) {
\t\t\tdev_err(adev->dev, "BC250 VCN postpower: firmware staging unavailable\\n");
\t\t\treturn -EINVAL;
\t\t}
\t\treload_ret = psp_execute_ip_fw_load(&adev->psp, ucode);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN postpower reload: ret=%d psp_status=%08x pgfsm=%08x power=%08x status=%08x reset=%08x cache=%08x fw=%08x%08x\\n",
\t\t\t reload_ret, adev->psp.cmd_buf_mem->resp.status,
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_VCPU_CACHE_64BIT_BAR_LOW),
\t\t\t ucode->tmr_mc_addr_hi, ucode->tmr_mc_addr_lo);
\t\tif (reload_ret || adev->psp.cmd_buf_mem->resp.status ||
\t\t    (ucode->tmr_mc_addr_hi == 0 && ucode->tmr_mc_addr_lo == 0)) {
\t\t\tucode->tmr_mc_addr_lo = old_lo;
\t\t\tucode->tmr_mc_addr_hi = old_hi;
\t\t\treturn reload_ret ? reload_ret : -EIO;
\t\t}
\t}

\t/* set uvd status busy */'''


def main():
    data = SOURCE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA, 'Source changed'
    source = data.decode()
    assert source.count(BEFORE) == 1, 'Injection anchor missing or ambiguous'
    result = source.replace(BEFORE, AFTER)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(result)
    print(DEST)
    print(hashlib.sha256(result.encode()).hexdigest())


if __name__ == '__main__':
    main()
