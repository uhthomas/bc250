#!/usr/bin/env python3
"""Add read-only phase snapshots to the pinned BC250 direct-BO VCN probe."""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-direct-bo-powered-20260928/vcn_v2_0.c'
DEST = BUILD / 'vcn-startup-phase-20260929/vcn_v2_0.c'
SOURCE_SHA = '68078fd630e42b37964f4c56614617000b2b1bd163210c30904b950180291644'

HELPER_ANCHOR = 'static void vcn_v2_0_set_dec_ring_funcs(struct amdgpu_device *adev);'
HELPER = '''static void bc250_vcn_phase(struct amdgpu_device *adev, const char *phase)
{
\tif (adev->pdev->device != 0x13fe ||
\t    adev->asic_type != CHIP_CYAN_SKILLFISH ||
\t    amdgpu_ip_version(adev, UVD_HWIP, 0) != IP_VERSION(2, 0, 3))
\t\treturn;

\tdev_warn(adev->dev,
\t\t "BC250 VCN phase %s: pgcfg=%08x pgstat=%08x power=%08x version=%08x reset=%08x cache=%08x pgflags=%llx\\n",
\t\t phase,
\t\t RREG32_SOC15(UVD, 0, mmUVD_PGFSM_CONFIG),
\t\t RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS),
\t\t RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS),
\t\t RREG32_SOC15(UVD, 0, mmUVD_VERSION),
\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET),
\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_VCPU_CACHE_64BIT_BAR_LOW),
\t\t (unsigned long long)adev->pg_flags);
}

'''


def replace_once(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, old[:120]
    return source.replace(old, new, 1)


def main() -> None:
    data = SOURCE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA
    source = data.decode()
    source = replace_once(source, HELPER_ANCHOR, HELPER + HELPER_ANCHOR)
    source = replace_once(source,
                          '\tstruct amdgpu_fw_shared *fw_shared;\n\n\t/* VCN DEC TRAP */',
                          '\tstruct amdgpu_fw_shared *fw_shared;\n\n'
                          '\tbc250_vcn_phase(adev, "sw-entry");\n\n\t/* VCN DEC TRAP */')
    source = replace_once(source,
                          '\tr = amdgpu_vcn_sw_init(adev, 0);\n\tif (r)\n\t\treturn r;\n\n'
                          '\tamdgpu_vcn_setup_ucode(adev, 0);',
                          '\tr = amdgpu_vcn_sw_init(adev, 0);\n\tif (r)\n\t\treturn r;\n'
                          '\tbc250_vcn_phase(adev, "after-vcn-sw-init");\n\n'
                          '\tamdgpu_vcn_setup_ucode(adev, 0);')
    source = replace_once(source,
                          '\tr = amdgpu_vcn_resume(adev, 0);\n\tif (r)\n\t\treturn r;\n\n'
                          '\tring = &adev->vcn.inst->ring_dec;',
                          '\tr = amdgpu_vcn_resume(adev, 0);\n\tif (r)\n\t\treturn r;\n'
                          '\tbc250_vcn_phase(adev, "after-vcn-resume");\n\n'
                          '\tring = &adev->vcn.inst->ring_dec;')
    source = replace_once(source,
                          '\tif (adev->pm.dpm_enabled)\n\t\tamdgpu_dpm_enable_vcn(adev, true, 0);\n\n'
                          '\tif (adev->pg_flags & AMD_PG_SUPPORT_VCN_DPG)',
                          '\tbc250_vcn_phase(adev, "start-entry");\n'
                          '\tif (adev->pm.dpm_enabled)\n\t\tamdgpu_dpm_enable_vcn(adev, true, 0);\n'
                          '\tbc250_vcn_phase(adev, "after-smu-power-call");\n\n'
                          '\tif (adev->pg_flags & AMD_PG_SUPPORT_VCN_DPG)')
    source = replace_once(source,
                          '\tvcn_v2_0_disable_static_power_gating(vinst);\n\n'
                          '\t/* set uvd status busy */',
                          '\tvcn_v2_0_disable_static_power_gating(vinst);\n'
                          '\tbc250_vcn_phase(adev, "after-local-pg");\n\n'
                          '\t/* set uvd status busy */')
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST, hashlib.sha256(DEST.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
