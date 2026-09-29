#!/usr/bin/env python3
"""Select direct VCN firmware BO loading in the measured powered state."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "output/video-decode-20260922/kernel-build"
VCN_SOURCE = BUILD / "vcn-psp-driver-20260927/amdgpu_vcn.c"
V2_SOURCE = BUILD / "vcn-direct-reset-after-psp-20260928/vcn_v2_0.c"
DEST = BUILD / "vcn-direct-bo-powered-20260928"
VCN_SHA = "6fc1584109ef3b782b37a211a84585e21b1a8268e624adff86370dbdaaa8d983"
V2_SHA = "700ce6297e2bbac55a8317159ce209d3ca42743e43f5d3154498a67f9de17c88"

VCN_OLD = '''bool amdgpu_vcn_fw_load_via_psp(struct amdgpu_device *adev)
{
\treturn adev->firmware.load_type == AMDGPU_FW_LOAD_PSP;
}
'''
VCN_NEW = '''bool amdgpu_vcn_fw_load_via_psp(struct amdgpu_device *adev)
{
\t/* Opt-in BC250 trial: copy the pinned navi10 VCN image into the
\t * ordinary VCPU BO instead of asking PSP to map its TMR copy.
\t */
\tif (adev->pdev->device == 0x13fe)
\t\treturn false;
\treturn adev->firmware.load_type == AMDGPU_FW_LOAD_PSP;
}
'''
PSP_BLOCK_START = '''\tif (adev->pdev->device == 0x13fe) {
\t\tstruct amdgpu_firmware_info *ucode =
\t\t\t&adev->firmware.ucode[AMDGPU_UCODE_ID_VCN];
'''
PSP_BLOCK_END = '''\n\tif (adev->pdev->device == 0x13fe)
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN trace mc:'''
DIRECT_BLOCK = '''\tif (adev->pdev->device == 0x13fe) {
\t\tif (amdgpu_vcn_fw_load_via_psp(adev)) {
\t\t\tdev_err(adev->dev, "BC250 VCN direct BO guard: PSP path selected\\n");
\t\t\treturn -EINVAL;
\t\t}
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN direct BO: gpu=%016llx fw_size=%zu version=%08x power=%08x pgfsm=%08x\\n",
\t\t\t (unsigned long long)adev->vcn.inst[0].gpu_addr,
\t\t\t adev->vcn.inst[0].fw->size,
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VERSION),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS));
\t}
'''


def main():
    vcn_bytes = VCN_SOURCE.read_bytes()
    v2_bytes = V2_SOURCE.read_bytes()
    assert hashlib.sha256(vcn_bytes).hexdigest() == VCN_SHA
    assert hashlib.sha256(v2_bytes).hexdigest() == V2_SHA
    vcn = vcn_bytes.decode()
    v2 = v2_bytes.decode()
    assert vcn.count(VCN_OLD) == 1
    vcn = vcn.replace(VCN_OLD, VCN_NEW)
    assert v2.count(PSP_BLOCK_START) == 1
    start = v2.index(PSP_BLOCK_START)
    end = v2.index(PSP_BLOCK_END, start)
    v2 = v2[:start] + DIRECT_BLOCK + v2[end:]
    DEST.mkdir(parents=True, exist_ok=True)
    for name, content in (("amdgpu_vcn.c", vcn), ("vcn_v2_0.c", v2)):
        (DEST / name).write_text(content)
        print(name, hashlib.sha256(content.encode()).hexdigest())


if __name__ == "__main__":
    main()
