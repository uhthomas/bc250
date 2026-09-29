#!/usr/bin/env python3
"""Instrument the pinned ordinary-BO startup with VCN LMI latency samples.

Only the three documented LAT_CTRL START bits are added to the existing
register value. The signed PSP mapping profile and VCN firmware are unchanged.
"""

import hashlib

import prepare_vcn_psp_bo_fetch as bo


SOURCE = bo.DEST / 'vcn_v2_0.c'
SOURCE_SHA = '3652327700e4c05132ad0f9ee2ceb3bc4a6f4991981f36d96ff58aedf75c9f1b'
DEST = bo.BUILD / 'vcn-lmi-latency-20260929'
PRE_ANCHOR = '\t/* On this BC250 UVD_SOFT_RESET reads as all ones. Avoid carrying\n'
RELEASE_ANCHOR = '\tfor (i = 0; i < 10; ++i) {\n'
WAIT_ANCHOR = '\t\tr = 0;\n\t\tif (status & 2)\n'


def sample(phase: str, indent: str) -> str:
    return f'''{indent}dev_warn(adev->dev,
{indent}\t "BC250 VCN LMI monitor {phase}: ctrl=%08x lat=%08x avg=%08x perfctrl=%08x countlo=%08x counthi=%08x mpc0=%08x mpc1=%08x\\n",
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CTRL),
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CNTR),
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_LMI_AVG_LAT_CNTR),
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_CTRL),
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_LO),
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_LMI_PERFMON_COUNT_HI),
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_MPC_PERF0),
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_MPC_PERF1));
'''


def main() -> None:
    source = bo.read_pinned(SOURCE, SOURCE_SHA)
    for label, anchor in (('pre', PRE_ANCHOR), ('release', RELEASE_ANCHOR),
                          ('wait', WAIT_ANCHOR)):
        if source.count(anchor) != 1:
            raise ValueError(f'{label} anchor not unique')

    pre = '''\tif (adev->pdev->device == 0x13fe) {
\t\tu32 lat_ctrl;

\t\tif (RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS) != 0x800 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS) != 0 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_VERSION) != 0x2001b)
\t\t\treturn -EINVAL;
'''
    pre += sample('before', '\t\t')
    pre += '''\t\tlat_ctrl = RREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CTRL);
\t\tif (lat_ctrl == 0xffffffff)
\t\t\treturn -EIO;
\t\t/* START fields are bits 8..10 in the VCN 2.0 register table.
\t\t * Preserve all other fields and do a single volatile write.
\t\t */
\t\tWREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CTRL, lat_ctrl | 0x700);
'''
    pre += sample('armed', '\t\t') + '\t}\n\n'
    source = source.replace(PRE_ANCHOR, pre + PRE_ANCHOR, 1)

    release = '\tif (adev->pdev->device == 0x13fe)\n' + sample('release', '\t\t') + '\n'
    source = source.replace(RELEASE_ANCHOR, release + RELEASE_ANCHOR, 1)

    wait = '\t\tif (adev->pdev->device == 0x13fe && i == 0)\n' + sample('wait0', '\t\t\t')
    source = source.replace(WAIT_ANCHOR, wait + WAIT_ANCHOR, 1)

    DEST.mkdir(parents=True, exist_ok=True)
    contents = {
        'amdgpu_vcn.c': bo.read_pinned(
            bo.DEST / 'amdgpu_vcn.c',
            '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'),
        'vcn_v2_0.c': source,
    }
    for name, content in contents.items():
        path = DEST / name
        if path.exists() and path.read_text() != content:
            raise ValueError(f'candidate already exists with different contents: {path}')
        if not path.exists():
            path.write_text(content)
        print(name, hashlib.sha256(content.encode()).hexdigest())


if __name__ == '__main__':
    main()
