#!/usr/bin/env python3
"""Calibrate VCN VCPU clock status with reversible post-PSP controls."""

import hashlib

import prepare_vcn_psp_bo_fetch as bo


SOURCE = bo.DEST / 'vcn_v2_0.c'
SOURCE_SHA = '3652327700e4c05132ad0f9ee2ceb3bc4a6f4991981f36d96ff58aedf75c9f1b'
DEST = bo.BUILD / 'vcn-clock-gate-probe-v2-20260929'
PRE_ANCHOR = '\t/* On this BC250 UVD_SOFT_RESET reads as all ones. Avoid carrying\n'
RELEASE_ANCHOR = '\tfor (i = 0; i < 10; ++i) {\n'
WAIT_ANCHOR = '\t\tr = 0;\n\t\tif (status & 2)\n'


def sample(phase: str, indent: str) -> str:
    return f'''{indent}dev_warn(adev->dev,
{indent}\t "BC250 VCN clock gate {phase}: vcpu=%08x gate=%08x ctrl=%08x status=%08x\\n",
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL),
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE),
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL),
{indent}\t RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS));
'''


def main() -> None:
    source = bo.read_pinned(SOURCE, SOURCE_SHA)
    for label, anchor in (('pre', PRE_ANCHOR), ('release', RELEASE_ANCHOR),
                          ('wait', WAIT_ANCHOR)):
        if source.count(anchor) != 1:
            raise ValueError(f'{label} anchor not unique')

    pre = '''\tif (adev->pdev->device == 0x13fe) {
\t\tu32 vcpu, gate, ctrl, status;

\t\tif (RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS) != 0x800 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS) != 0 ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_VERSION) != 0x2001b ||
\t\t    RREG32_SOC15(UVD, 0, mmCC_UVD_HARVESTING) != 3)
\t\t\treturn -EINVAL;
\t\tvcpu = RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL);
\t\tgate = RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE);
\t\tctrl = RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL);
\t\tstatus = RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN clock gate guard: vcpu=%08x gate=%08x ctrl=%08x status=%08x\\n",
\t\t\t vcpu, gate, ctrl, status);
\t\tif (vcpu != 0x0ff20200 || gate == 0xffffffff ||
\t\t    (gate & UVD_CGC_GATE__VCPU_MASK) ||
\t\t    ctrl == 0xffffffff ||
\t\t    (ctrl & UVD_CGC_CTRL__VCPU_MODE_MASK) ||
\t\t    status == 0xffffffff)
\t\t\treturn -EINVAL;
'''
    pre += sample('before', '\t\t')
    pre += '''\t\t/* The signed PSP hook has already requested reset release.
\t\t * The previous bounded trial established CLK_EN is writable.
\t\t */
\t\tWREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL,
\t\t\t       vcpu & ~UVD_VCPU_CNTL__CLK_EN_MASK);
\t\tudelay(10);
'''
    pre += sample('clock-off', '\t\t')
    pre += '''\t\tWREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL, vcpu);
\t\tudelay(10);
'''
    pre += sample('clock-restored', '\t\t')
    pre += '''\t\tif (RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != vcpu)
\t\t\treturn -EIO;
\t\t/* Linux cleared this one gate in disable_clock_gating().
\t\t * Set only VCPU briefly, then restore the original word.
\t\t */
\t\tWREG32_SOC15(UVD, 0, mmUVD_CGC_GATE,
\t\t\t       gate | UVD_CGC_GATE__VCPU_MASK);
\t\tudelay(10);
'''
    pre += sample('gate-on', '\t\t')
    pre += '''\t\tWREG32_SOC15(UVD, 0, mmUVD_CGC_GATE, gate);
\t\tudelay(10);
'''
    pre += sample('gate-restored', '\t\t')
    pre += '''\t\tif (RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE) != gate ||
\t\t    RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != vcpu)
\t\t\treturn -EIO;
\t}

'''
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
