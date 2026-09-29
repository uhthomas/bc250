#!/usr/bin/env python3
"""Enable and restore the VCN PIF address-error routes during a BAR trial.

The source is the guarded out-of-VRAM BAR differential. This variant arms
only the named PIF bit in the SYS and VCPU enable registers and records
whether those bits survive VCPU reset release. All changes are volatile.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-vcpu-address-fault-20260929/vcn_v2_0.c'
SOURCE_SHA = '7be776962f21d5100869f8d986830f0783861eb36524899886a9ebfd7f617a4b'
VCN = BUILD / 'vcn-vcpu-address-fault-20260929/amdgpu_vcn.c'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'
DEST = BUILD / 'vcn-vcpu-pif-interrupt-20260929'


def replace_n(source: str, old: str, new: str, expected: int = 1) -> str:
    count = source.count(old)
    if count != expected:
        raise ValueError(f'PIF interrupt anchor count {count}!={expected}: {old[:72]!r}')
    return source.replace(old, new)


def main() -> None:
    source = SOURCE.read_bytes()
    vcn = VCN.read_bytes()
    if (hashlib.sha256(source).hexdigest() != SOURCE_SHA or
            hashlib.sha256(vcn).hexdigest() != VCN_SHA):
        raise ValueError('pinned VCPU address-error source changed')
    candidate = source.decode()
    candidate = replace_n(candidate,
        '\t\tu32 rptr_changes = 0, lmi_changes = 0;\n',
        '\t\tu32 rptr_changes = 0, lmi_changes = 0;\n'
        '\t\tu32 old_sys_int_en, old_vcpu_int_en;\n')
    held = ('\t\tdev_warn(adev->dev,\n'
            '\t\t\t "BC250 VCPU address fault held: sys=%08x en=%08x trce_rd=%08x\\n",\n'
            '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SYS_INT_STATUS),\n'
            '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SYS_INT_EN),\n'
            '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE_RD));\n')
    armed = held + (
        '\t\told_sys_int_en = RREG32_SOC15(UVD, 0, mmUVD_SYS_INT_EN);\n'
        '\t\told_vcpu_int_en = RREG32_SOC15(UVD, 0, mmUVD_VCPU_INT_EN);\n'
        '\t\tWREG32_SOC15(UVD, 0, mmUVD_SYS_INT_EN,\n'
        '\t\t\t old_sys_int_en | UVD_SYS_INT_EN__PIF_ADDR_ERR_EN_MASK);\n'
        '\t\tWREG32_SOC15(UVD, 0, mmUVD_VCPU_INT_EN,\n'
        '\t\t\t old_vcpu_int_en | UVD_VCPU_INT_EN__PIF_ADDR_ERR_EN_MASK);\n'
        '\t\tdev_warn(adev->dev,\n'
        '\t\t\t "BC250 VCPU PIF armed: old_sys=%08x old_vcpu=%08x sys=%08x vcpu=%08x master=%08x status=%08x\\n",\n'
        '\t\t\t old_sys_int_en, old_vcpu_int_en,\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SYS_INT_EN),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_INT_EN),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_MASTINT_EN),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SYS_INT_STATUS));\n')
    candidate = replace_n(candidate, held, armed)
    for phase in ('displaced', 'restored'):
        anchor = f'\t\t\tdev_warn(adev->dev,\n\t\t\t\t "BC250 VCPU address fault {phase}:'
        candidate = replace_n(candidate, anchor,
            '\t\t\tdev_warn(adev->dev,\n'
            f'\t\t\t\t "BC250 VCPU PIF {phase} enable: sys=%08x vcpu=%08x master=%08x\\n",\n'
            '\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SYS_INT_EN),\n'
            '\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_INT_EN),\n'
            '\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_MASTINT_EN));\n'
            + anchor)
    restore_anchor = ('\t\t/* Read the restored BAR before the signed driver\'s map replay.\n')
    candidate = replace_n(candidate, restore_anchor,
        '\t\tWREG32_SOC15(UVD, 0, mmUVD_VCPU_INT_EN, old_vcpu_int_en);\n'
        '\t\tWREG32_SOC15(UVD, 0, mmUVD_SYS_INT_EN, old_sys_int_en);\n'
        '\t\tdev_warn(adev->dev,\n'
        '\t\t\t "BC250 VCPU PIF disarmed: sys=%08x vcpu=%08x status=%08x\\n",\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SYS_INT_EN),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_INT_EN),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SYS_INT_STATUS));\n\n'
        + restore_anchor)
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
