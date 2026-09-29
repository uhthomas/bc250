#!/usr/bin/env python3
"""Bracket PSP startup operations with read-only BC250 VCN MMIO snapshots."""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'late-psp-probe-20260927/amdgpu_psp.c'
DEST = BUILD / 'vcn-psp-phase-20260929/amdgpu_psp.c'
SOURCE_SHA = '9d574280fa9f76b6adbec4c3fb971a2c16e9c8614a150b07c8e92759f5a3e62e'


def replace_once(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, old[:100]
    return source.replace(old, new, 1)


def rewrite_region(source: str, start: str, end: str, change) -> str:
    first = source.index(start)
    last = source.index(end, first + len(start))
    region = source[first:last]
    return source[:first] + change(region) + source[last:]


HELPER = '''static void bc250_vcn_psp_phase(struct amdgpu_device *adev,
                                 const char *phase)
{
\tif (adev->pdev->device != 0x13fe ||
\t    adev->asic_type != CHIP_CYAN_SKILLFISH ||
\t    amdgpu_ip_version(adev, UVD_HWIP, 0) != IP_VERSION(2, 0, 3))
\t\treturn;

\tdev_warn(adev->dev,
\t\t "BC250 VCN PSP phase %s: pgstat=%08x power=%08x version=%08x\\n",
\t\t phase,
\t\t RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS),
\t\t RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS),
\t\t RREG32_SOC15(UVD, 0, mmUVD_VERSION));
}

'''


def main() -> None:
    data = SOURCE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA
    source = data.decode()
    source = replace_once(source, '#include "soc15_common.h"\n',
                          '#include "soc15_common.h"\n#include "soc15.h"\n'
                          '#include "vcn/vcn_2_0_0_offset.h"\n')
    source = replace_once(source, 'static int psp_hw_start(struct psp_context *psp)',
                          HELPER + 'static int psp_hw_start(struct psp_context *psp)')

    def hw_start(region: str) -> str:
        region = replace_once(region,
                              '\tif (amdgpu_virt_xgmi_migrate_enabled(adev))\n',
                              '\tbc250_vcn_psp_phase(adev, "hw-start-entry");\n'
                              '\tif (amdgpu_virt_xgmi_migrate_enabled(adev))\n')
        for name in ('kdb', 'spl', 'sysdrv', 'soc_drv', 'intf_drv',
                     'dbg_drv', 'ras_drv', 'ipkeymgr_drv', 'spdm_drv', 'sos'):
            old = f'\t\t\tret = psp_bootloader_load_{name}(psp);\n'
            new = old + f'\t\t\tbc250_vcn_psp_phase(adev, "after-bootloader-{name}");\n'
            region = replace_once(region, old, new)
        for call, phase in (
            ('psp_ring_create(psp, PSP_RING_TYPE__KM)', 'after-ring-create'),
            ('psp_update_fw_reservation(psp)', 'after-fw-reservation'),
            ('psp_tmr_init(psp)', 'after-tmr-init'),
            ('psp_load_smu_fw(psp)', 'after-smu-fw'),
            ('psp_tmr_load(psp)', 'after-tmr-load'),
        ):
            old = f'ret = {call};\n'
            new = old + f'\tbc250_vcn_psp_phase(adev, "{phase}");\n'
            region = replace_once(region, old, new)
        return region

    source = rewrite_region(source, 'static int psp_hw_start(',
                            'int amdgpu_psp_get_fw_type(', hw_start)

    def load_fw(region: str) -> str:
        for call, phase in (
            ('psp_ring_init(psp, PSP_RING_TYPE__KM)', 'after-ring-init'),
            ('psp_hw_start(psp)', 'after-hw-start'),
            ('psp_load_non_psp_fw(psp)', 'after-non-psp-fw'),
            ('psp_asd_initialize(psp)', 'after-asd'),
            ('psp_rl_load(adev)', 'after-rl'),
        ):
            old = f'\tret = {call};\n'
            new = old + f'\tbc250_vcn_psp_phase(adev, "{phase}");\n'
            region = replace_once(region, old, new)
        return region

    source = rewrite_region(source, 'static int psp_load_fw(',
                            'static int psp_hw_init(', load_fw)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST, hashlib.sha256(DEST.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
