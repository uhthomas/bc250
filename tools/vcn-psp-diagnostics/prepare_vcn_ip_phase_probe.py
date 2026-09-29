#!/usr/bin/env python3
"""Bracket BC250 GPU IP hardware init with read-only VCN MMIO snapshots."""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'linux-7.2.5/drivers/gpu/drm/amd/amdgpu/amdgpu_device.c'
DEST = BUILD / 'vcn-ip-phase-20260929/amdgpu_device.c'
SOURCE_SHA = '42b089ec977648f19c780d90c3eca271306c5826b62e4a7ac0bb5a3904f8c876'


def replace_once(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, old[:100]
    return source.replace(old, new, 1)


def rewrite_region(source: str, start: str, end: str, change) -> str:
    first = source.index(start)
    last = source.index(end, first + len(start))
    region = source[first:last]
    return source[:first] + change(region) + source[last:]


HELPER = '''static void bc250_vcn_ip_phase(struct amdgpu_device *adev,
                                const char *phase, const char *block)
{
\tif (adev->pdev->device != 0x13fe ||
\t    adev->asic_type != CHIP_CYAN_SKILLFISH ||
\t    amdgpu_ip_version(adev, UVD_HWIP, 0) != IP_VERSION(2, 0, 3))
\t\treturn;

\tdev_warn(adev->dev,
\t\t "BC250 VCN IP phase %s block=%s: pgstat=%08x power=%08x version=%08x\\n",
\t\t phase, block,
\t\t RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS),
\t\t RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS),
\t\t RREG32_SOC15(UVD, 0, mmUVD_VERSION));
}

'''


def main() -> None:
    data = SOURCE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA
    source = data.decode()
    source = replace_once(source, '#include "soc15.h"\n',
                          '#include "soc15.h"\n#include "vcn/vcn_2_0_0_offset.h"\n')
    source = replace_once(source,
                          'static int amdgpu_device_ip_hw_init_phase1(struct amdgpu_device *adev)',
                          HELPER + 'static int amdgpu_device_ip_hw_init_phase1(struct amdgpu_device *adev)')

    def phase2(region: str) -> str:
        old = '\t\tr = adev->ip_blocks[i].version->funcs->hw_init(&adev->ip_blocks[i]);\n'
        new = ('\t\tbc250_vcn_ip_phase(adev, "phase2-before",\n'
               '\t\t\tadev->ip_blocks[i].version->funcs->name);\n' + old)
        region = replace_once(region, old, new)
        old = '\t\tadev->ip_blocks[i].status.hw = true;\n'
        new = old + ('\t\tbc250_vcn_ip_phase(adev, "phase2-after",\n'
                     '\t\t\tadev->ip_blocks[i].version->funcs->name);\n')
        return replace_once(region, old, new)

    source = rewrite_region(source,
                            'static int amdgpu_device_ip_hw_init_phase2(',
                            'static int amdgpu_device_fw_loading(', phase2)

    def fw_loading(region: str) -> str:
        region = replace_once(region, '\tif (adev->asic_type >= CHIP_VEGA10) {\n',
                              '\tbc250_vcn_ip_phase(adev, "before-psp", "psp");\n'
                              '\tif (adev->asic_type >= CHIP_VEGA10) {\n')
        region = replace_once(region,
                              '\tif (!amdgpu_sriov_vf(adev) || adev->asic_type == CHIP_TONGA)\n',
                              '\tbc250_vcn_ip_phase(adev, "after-psp", "psp");\n'
                              '\tif (!amdgpu_sriov_vf(adev) || adev->asic_type == CHIP_TONGA)\n')
        region = replace_once(region,
                              '\t\tr = amdgpu_pm_load_smu_firmware(adev, &smu_version);\n',
                              '\t\tr = amdgpu_pm_load_smu_firmware(adev, &smu_version);\n'
                              '\tbc250_vcn_ip_phase(adev, "after-smu-firmware", "smu");\n')
        return region

    source = rewrite_region(source, 'static int amdgpu_device_fw_loading(',
                            'static int amdgpu_device_init_schedulers(', fw_loading)

    def ip_init(region: str) -> str:
        for call, before, after in (
            ('amdgpu_device_ip_hw_init_phase1', 'after-sw-init', 'after-phase1'),
            ('amdgpu_device_fw_loading', 'before-fw-loading', 'after-fw-loading'),
            ('amdgpu_device_ip_hw_init_phase2', 'before-phase2', 'after-phase2'),
        ):
            old = f'\tr = {call}(adev);\n\tif (r)\n\t\tgoto init_failed;\n'
            new = (f'\tbc250_vcn_ip_phase(adev, "{before}", "-");\n'
                   + old + f'\tbc250_vcn_ip_phase(adev, "{after}", "-");\n')
            region = replace_once(region, old, new)
        return region

    source = rewrite_region(source, 'static int amdgpu_device_ip_init(',
                            'void amdgpu_device_fill_reset_magic', ip_init)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST, hashlib.sha256(DEST.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
