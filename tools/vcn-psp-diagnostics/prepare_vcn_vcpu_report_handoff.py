#!/usr/bin/env python3
"""Force the writable VCPU report just long enough to test driver handoff.

The diagnostic boots in isolation, the module changes only volatile VCN
registers, and the Pi PDU wrapper cold-cycles the board after collecting
the real decode-ring test result. A forced ready bit is never treated as
proof of VCPU execution.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-vcpu-report-force-20260929/vcn_v2_0.c'
SOURCE_SHA = 'd69ab73839c4458c1ca88959479010991908dd6492dc9bf4769e356a20bfabc0'
VCN = BUILD / 'vcn-vcpu-report-force-20260929/amdgpu_vcn.c'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'
DEST = BUILD / 'vcn-vcpu-report-handoff-20260929'


def replace_n(source: str, old: str, new: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f'VCPU handoff anchor count {count}: {old[:70]!r}')
    return source.replace(old, new)


def main() -> None:
    source = SOURCE.read_bytes()
    vcn = VCN.read_bytes()
    if (hashlib.sha256(source).hexdigest() != SOURCE_SHA or
            hashlib.sha256(vcn).hexdigest() != VCN_SHA):
        raise ValueError('pinned VCPU report source changed')
    candidate = source.decode()
    candidate = replace_n(candidate,
        'for (phase = 0; phase < 4; ++phase)',
        'for (phase = 0; phase < 5; ++phase)')
    candidate = replace_n(candidate,
        '\t\tu32 idle_cntl, run_cntl, phase, word, rptr, marker;\n',
        '\t\tu32 idle_cntl, run_cntl, phase, word, rptr, marker;\n'
        '\t\tbool handoff_ok;\n')
    candidate = replace_n(candidate,
        '\t\t/* Preserve the driver\'s pending wait semantics even if a ring\n'
        '\t\t * packet failed. This is the value the driver set before our probe.\n'
        '\t\t */\n'
        '\t\tWREG32_SOC15(UVD, 0, mmUVD_STATUS, status);\n',
        '\t\t/* Only hand off the forced ready report if the fifth ring\n'
        '\t\t * packet reached its exact marker. Otherwise restore BUSY.\n'
        '\t\t */\n'
        '\t\thandoff_ok = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR) == 80 &&\n'
        '\t\t\t     RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9) == 0x11110004;\n'
        '\t\tif (!handoff_ok)\n'
        '\t\t\tWREG32_SOC15(UVD, 0, mmUVD_STATUS, status);\n')
    candidate = replace_n(candidate,
        'BC250 VCPU report final:',
        'BC250 VCPU report handoff:')
    candidate = replace_n(candidate,
        '\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, old_cntl);\n'
        '\t}\n\n\n\tfor (i = 0; i < 10; ++i) {',
        '\t\tWREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, old_cntl);\n'
        '\t\tif (!handoff_ok)\n'
        '\t\t\treturn -EIO;\n'
        '\t}\n\n\n\tfor (i = 0; i < 10; ++i) {')
    candidate = replace_n(candidate,
        '\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_MASTINT_EN),\n'
        '\t\tUVD_MASTINT_EN__VCPU_EN_MASK,\n'
        '\t\t~UVD_MASTINT_EN__VCPU_EN_MASK);\n\n'
        '\t/* clear the busy bit of VCN_STATUS */',
        '\tWREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_MASTINT_EN),\n'
        '\t\tUVD_MASTINT_EN__VCPU_EN_MASK,\n'
        '\t\t~UVD_MASTINT_EN__VCPU_EN_MASK);\n'
        '\tif (adev->pdev->device == 0x13fe)\n'
        '\t\tdev_warn(adev->dev,\n'
        '\t\t\t "BC250 VCPU report after wait: status=%08x master=%08x prid=%08x pc=%08x\\n",\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_MASTINT_EN),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE));\n\n'
        '\t/* clear the busy bit of VCN_STATUS */')
    candidate = replace_n(candidate,
        '\tr = amdgpu_ring_test_helper(ring);\n\tif (r)\n\t\treturn r;',
        '\tr = amdgpu_ring_test_helper(ring);\n'
        '\tif (adev->pdev->device == 0x13fe)\n'
        '\t\tdev_warn(adev->dev,\n'
        '\t\t\t "BC250 VCPU report decode test: ret=%d status=%08x master=%08x rptr=%08x wptr=%08x scratch=%08x prid=%08x pc=%08x\\n",\n'
        '\t\t\t r, RREG32_SOC15(UVD, 0, mmUVD_STATUS),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_MASTINT_EN),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE));\n'
        '\tif (r)\n\t\treturn r;')
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in (('vcn_v2_0.c', candidate.encode()),
                       ('amdgpu_vcn.c', vcn)):
        path = DEST / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_bytes(data)
        print(name, hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    main()
