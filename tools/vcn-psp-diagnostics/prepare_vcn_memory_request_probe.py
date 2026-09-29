#!/usr/bin/env python3
"""Add bounded VCN LMI outstanding-request sampling to the pinned BO trial.

The probe reads only VCN-local MMIO after VCPU release. A clean-bit transition
is evidence of an in-flight request; an unchanged value cannot prove none.
"""

import hashlib

import prepare_vcn_psp_bo_fetch as bo


SOURCE = bo.BUILD / 'vcn-lmi-latency-20260929' / 'vcn_v2_0.c'
SOURCE_SHA = 'f489f10e7dc6699e2a5c7dd46c14b4247920a5ac8d57e1bb15d381da97c57c6b'
DEST = bo.BUILD / 'vcn-memory-requests-20260929'
ANCHOR = '\tfor (i = 0; i < 10; ++i) {\n'


def main() -> None:
    source = bo.read_pinned(SOURCE, SOURCE_SHA)
    if source.count(ANCHOR) != 1:
        raise ValueError('release-loop anchor changed')
    source = source.replace('#include <linux/firmware.h>\n',
                            '#include <linux/firmware.h>\n#include <linux/delay.h>\n', 1)
    sample = '''\tif (adev->pdev->device == 0x13fe) {
\t\tu32 before, first, last, bits_and, bits_or, transitions = 0;
\t\tunsigned int sample_i;

\t\t/* This is the VCN-local LMI status, not the root PCI SMN path.
\t\t * Sample for about 20 ms immediately after VCPU reset release.
\t\t * Leave all VCN register values and the normal wait loop intact.
\t\t */
\t\tbefore = RREG32_SOC15(UVD, 0, mmUVD_LMI_STATUS);
\t\tfirst = before;
\t\tlast = before;
\t\tbits_and = before;
\t\tbits_or = before;
\t\tfor (sample_i = 0; sample_i < 4096; ++sample_i) {
\t\t\tu32 value = RREG32_SOC15(UVD, 0, mmUVD_LMI_STATUS);

\t\t\tbits_and &= value;
\t\t\tbits_or |= value;
\t\t\ttransitions += value != last;
\t\t\tlast = value;
\t\t\tudelay(5);
\t\t}
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN LMI requests: samples=4096 before=%08x first=%08x last=%08x and=%08x or=%08x transitions=%u latency=%08x pc=%08x pf=%08x\\n",
\t\t\t before, first, last, bits_and, bits_or, transitions,
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CNTR),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS));
\t}

'''
    source = source.replace(ANCHOR, sample + ANCHOR, 1)
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
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_text(content)
        print(name, hashlib.sha256(content.encode()).hexdigest())


if __name__ == '__main__':
    main()
