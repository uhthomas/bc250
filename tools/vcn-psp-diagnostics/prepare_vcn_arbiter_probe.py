#!/usr/bin/env python3
"""Sample the pinned powered VCN's VCPU arbiter and memory controls."""

import hashlib

import prepare_vcn_psp_bo_fetch as bo


SOURCE = bo.DEST / 'vcn_v2_0.c'
SOURCE_SHA = '3652327700e4c05132ad0f9ee2ceb3bc4a6f4991981f36d96ff58aedf75c9f1b'
DEST = bo.BUILD / 'vcn-arbiter-probe-20260929'
PRE_ANCHOR = '\t/* On this BC250 UVD_SOFT_RESET reads as all ones. Avoid carrying\n'
RELEASE_ANCHOR = '\tfor (i = 0; i < 10; ++i) {\n'
WAIT_ANCHOR = '\t\tr = 0;\n\t\tif (status & 2)\n'


def sample(phase: str, indent: str) -> str:
    return f'''{indent}dev_warn(adev->dev,
{indent}\t "BC250 VCN arbiter {phase}: arb=%08x mpc=%08x vm=%08x cgc=%08x\\n",
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_RB_ARB_CTRL),
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_MPC_CNTL),
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_LMI_VM_CTRL),
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS));
'''


def main() -> None:
    source = bo.read_pinned(SOURCE, SOURCE_SHA)
    for label, anchor in (('pre', PRE_ANCHOR), ('release', RELEASE_ANCHOR),
                          ('wait', WAIT_ANCHOR)):
        if source.count(anchor) != 1:
            raise ValueError(f'{label} anchor not unique')
    pre = '''\tif (adev->pdev->device == 0x13fe) {
\t\tif (RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS) != 0x800 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS) != 0 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_VERSION) != 0x2001b)
\t\t\treturn -EINVAL;
'''
    pre += sample('before', '\t\t') + '\t}\n\n'
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
