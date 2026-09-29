#!/usr/bin/env python3
"""Build source for a default-off, JPEG-only BC250 media-island probe.

The opt-in `bc250_vcn=1` switch registers JPEG v2.0 alone on VCN IP 2.0.3.
JPEG has no VCPU firmware dependency. The experiment deliberately leaves the
VCN decoder unregistered and never alters the installed amdgpu module.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'linux-7.2.5/drivers/gpu/drm/amd/amdgpu'
DEST = BUILD / 'bc250-jpeg-only-20260929'
PINNED = {
    'amdgpu_discovery.c': '136d3add115e1b6afc0dac317ca25084313066a027bc54088f1f2221af786beb',
    'jpeg_v2_0.c': 'cd4b62c10aa403e73346c89afd5fa93cd71e0a734453c08cdb4c665be88f451e',
}

DISCOVERY_OLD = '''\t\tcase IP_VERSION(2, 0, 3):
\t\t\tif (amdgpu_vcn_bc250_experimental(adev)) {
\t\t\t\tdev_warn(adev->dev, "Experimental BC250 VCN direct-load path enabled\\n");
\t\t\t\tamdgpu_device_ip_block_add(adev, &vcn_v2_0_ip_block);
\t\t\t}
\t\t\tbreak;'''
DISCOVERY_NEW = '''\t\tcase IP_VERSION(2, 0, 3):
\t\t\tif (amdgpu_vcn_bc250_experimental(adev) &&
\t\t\t    !amdgpu_sriov_vf(adev)) {
\t\t\t\t/* Diagnostic: test the independent JPEG ring without
\t\t\t\t * registering VCN or requesting VCPU firmware.
\t\t\t\t */
\t\t\t\tdev_warn(adev->dev, "BC250 JPEG-only ring probe enabled\\n");
\t\t\t\tamdgpu_device_ip_block_add(adev, &jpeg_v2_0_ip_block);
\t\t\t}
\t\t\tbreak;'''

JPEG_OLD = '''\tif (adev->pm.dpm_enabled)
\t\tamdgpu_dpm_enable_jpeg(adev, true);

\t/* disable power gating */
\tr = jpeg_v2_0_disable_power_gating(adev);'''
JPEG_NEW = '''\tif (adev->pdev->device == 0x13fe) {
\t\tif (adev->asic_type != CHIP_CYAN_SKILLFISH ||
\t\t    amdgpu_ip_version(adev, UVD_HWIP, 0) != IP_VERSION(2, 0, 3)) {
\t\t\tdev_err(adev->dev, "BC250 JPEG guard rejected ASIC\\n");
\t\t\treturn -EINVAL;
\t\t}
\t\t/* Cyan Skillfish normally registers no JPEG IP and has no JPEG
\t\t * PG flag. This opt-in probe uses the standard v2.0 PG sequence.
\t\t */
\t\tadev->pg_flags |= AMD_PG_SUPPORT_JPEG;
\t\tdev_warn(adev->dev, "BC250 JPEG start: pg_flags=%llx\\n",
\t\t\t (unsigned long long)adev->pg_flags);
\t}

\tif (adev->pm.dpm_enabled)
\t\tamdgpu_dpm_enable_jpeg(adev, true);

\t/* disable power gating */
\tr = jpeg_v2_0_disable_power_gating(adev);'''

JPEG_PGFSM_OLD = '''\tif (adev->pg_flags & AMD_PG_SUPPORT_JPEG) {
\t\tdata = 1 << UVD_PGFSM_CONFIG__UVDJ_PWR_CONFIG__SHIFT;
\t\tWREG32(SOC15_REG_OFFSET(JPEG, 0, mmUVD_PGFSM_CONFIG), data);

\t\tr = SOC15_WAIT_ON_RREG(JPEG, 0,
\t\t\tmmUVD_PGFSM_STATUS, UVD_PGFSM_STATUS_UVDJ_PWR_ON,
\t\t\tUVD_PGFSM_STATUS__UVDJ_PWR_STATUS_MASK);

\t\tif (r) {
\t\t\tdrm_err(adev_to_drm(adev), "failed to disable JPEG power gating\\n");
\t\t\treturn r;
\t\t}
\t}'''
JPEG_PGFSM_NEW = '''\tif (adev->pg_flags & AMD_PG_SUPPORT_JPEG) {
\t\tif (adev->pdev->device == 0x13fe)
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 JPEG PG before: config=%08x status=%08x\\n",
\t\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_PGFSM_CONFIG),
\t\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_PGFSM_STATUS));
\t\tdata = 1 << UVD_PGFSM_CONFIG__UVDJ_PWR_CONFIG__SHIFT;
\t\tWREG32(SOC15_REG_OFFSET(JPEG, 0, mmUVD_PGFSM_CONFIG), data);
\t\tif (adev->pdev->device == 0x13fe)
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 JPEG PG request: wanted=%08x config=%08x status=%08x\\n",
\t\t\t\t data,
\t\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_PGFSM_CONFIG),
\t\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_PGFSM_STATUS));

\t\tr = SOC15_WAIT_ON_RREG(JPEG, 0,
\t\t\tmmUVD_PGFSM_STATUS, UVD_PGFSM_STATUS_UVDJ_PWR_ON,
\t\t\tUVD_PGFSM_STATUS__UVDJ_PWR_STATUS_MASK);

\t\tif (r) {
\t\t\tif (adev->pdev->device == 0x13fe)
\t\t\t\tdev_warn(adev->dev,
\t\t\t\t\t "BC250 JPEG PG timeout: config=%08x status=%08x\\n",
\t\t\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_PGFSM_CONFIG),
\t\t\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_PGFSM_STATUS));
\t\t\tdrm_err(adev_to_drm(adev), "failed to disable JPEG power gating\\n");
\t\t\treturn r;
\t\t}
\t}'''

JPEG_POST_PG_OLD = '''\tif (r)
\t\treturn r;

\t/* JPEG disable CGC */
\tjpeg_v2_0_disable_clock_gating(adev);'''
JPEG_POST_PG_NEW = '''\tif (r)
\t\treturn r;

\tif (adev->pdev->device == 0x13fe)
\t\tdev_warn(adev->dev,
\t\t\t "BC250 JPEG power: jpeg=%08x pgfsm=%08x version=%08x harvest=%08x jrbc=%08x\\n",
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JPEG_POWER_STATUS),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_PGFSM_STATUS),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_VERSION),
\t\t\t RREG32_SOC15(JPEG, 0, mmCC_UVD_HARVESTING),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_STATUS));

\t/* JPEG disable CGC */
\tjpeg_v2_0_disable_clock_gating(adev);'''

JPEG_END_OLD = '''\tring->wptr = RREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_WPTR);

\treturn 0;
}'''
JPEG_END_NEW = '''\tring->wptr = RREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_WPTR);

\tif (adev->pdev->device == 0x13fe)
\t\tdev_warn(adev->dev,
\t\t\t "BC250 JPEG ring: jrbc=%08x rptr=%08x wptr=%08x cgc=%08x gate=%08x\\n",
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_STATUS),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_RPTR),
\t\t\t RREG32_SOC15(JPEG, 0, mmUVD_JRBC_RB_WPTR),
\t\t\t RREG32_SOC15(JPEG, 0, mmJPEG_CGC_CTRL),
\t\t\t RREG32_SOC15(JPEG, 0, mmJPEG_CGC_GATE));

\treturn 0;
}'''


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, old[:80]
    return source.replace(old, new, 1)


def main() -> None:
    discovery_bytes = (SOURCE / 'amdgpu_discovery.c').read_bytes()
    jpeg_bytes = (SOURCE / 'jpeg_v2_0.c').read_bytes()
    assert digest(discovery_bytes) == PINNED['amdgpu_discovery.c']
    assert digest(jpeg_bytes) == PINNED['jpeg_v2_0.c']
    discovery = replace_once(discovery_bytes.decode(), DISCOVERY_OLD, DISCOVERY_NEW)
    jpeg = replace_once(jpeg_bytes.decode(), JPEG_OLD, JPEG_NEW)
    jpeg = replace_once(jpeg, JPEG_PGFSM_OLD, JPEG_PGFSM_NEW)
    jpeg = replace_once(jpeg, JPEG_POST_PG_OLD, JPEG_POST_PG_NEW)
    jpeg = replace_once(jpeg, JPEG_END_OLD, JPEG_END_NEW)
    assert discovery.count('amdgpu_device_ip_block_add(adev, &vcn_v2_0_ip_block);') == 1
    # The remaining reference is the normal VCN 2.0.0/2.0.2/2.2.0 path.
    assert 'BC250 JPEG-only ring probe enabled' in discovery
    assert 'adev->pg_flags |= AMD_PG_SUPPORT_JPEG;' in jpeg
    DEST.mkdir(parents=True, exist_ok=True)
    for name, content in (('amdgpu_discovery.c', discovery),
                          ('jpeg_v2_0.c', jpeg)):
        output = DEST / name
        output.write_text(content)
        print(name, digest(output.read_bytes()))


if __name__ == '__main__':
    main()
