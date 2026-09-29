#!/usr/bin/env python3
"""Read the DPG VCPU clock report across a guarded CLK_EN toggle."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-vcpu-clock-differential-20260929/vcn_v2_0.c'
SOURCE_SHA = '42be01e813a091ec863498cf0aee749f6f8ee95fdab6de66e1f49bae589533b1'
VCN = BUILD / 'vcn-vcpu-clock-differential-20260929/amdgpu_vcn.c'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'
DEST = BUILD / 'vcn-dpg-clock-report-20260929'


def once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'DPG report anchor changed: {old[:80]!r}')
    return source.replace(old, new, 1)


def main() -> None:
    source = SOURCE.read_bytes()
    vcn = VCN.read_bytes()
    if (hashlib.sha256(source).hexdigest() != SOURCE_SHA or
            hashlib.sha256(vcn).hexdigest() != VCN_SHA):
        raise ValueError('pinned VCPU clock source changed')
    candidate = source.decode()
    candidate = once(candidate,
        '\t\t\tu32 ctrl_off, cgc_off, ctrl_back, cgc_back;',
        '\t\t\tu32 ctrl_off, cgc_off, ctrl_back, cgc_back;\n'
        '\t\t\tu32 report_off, report_back;')
    candidate = once(candidate,
        '\t\t\tu32 cgc_on = RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS);',
        '\t\t\tu32 cgc_on = RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS);\n'
        '\t\t\tu32 report_on = RREG32_SOC15(UVD, 0, mmUVD_DPG_CLK_EN_VCPU_REPORT);')
    candidate = once(candidate,
        '\t\t\tcgc_off = RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS);',
        '\t\t\tcgc_off = RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS);\n'
        '\t\t\treport_off = RREG32_SOC15(UVD, 0, mmUVD_DPG_CLK_EN_VCPU_REPORT);')
    candidate = once(candidate,
        '\t\t\tcgc_back = RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS);',
        '\t\t\tcgc_back = RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS);\n'
        '\t\t\treport_back = RREG32_SOC15(UVD, 0, mmUVD_DPG_CLK_EN_VCPU_REPORT);')
    candidate = once(candidate,
        'ctrl_back=%08x prid=%08x\\n",',
        'ctrl_back=%08x prid=%08x dpg_on=%08x dpg_off=%08x dpg_back=%08x\\n",')
    candidate = once(candidate,
        'RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID));\n\t\t\tif (ctrl_off',
        'RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),\n'
        '\t\t\t\t report_on, report_off, report_back);\n\t\t\tif (ctrl_off')
    candidate = once(candidate,
        'BC250 VCPU clock released: gate=%08x cgcctrl=%08x cgc=%08x ctrl=%08x prid=%08x pc=%08x status=%08x\\n",',
        'BC250 VCPU clock released: gate=%08x cgcctrl=%08x cgc=%08x ctrl=%08x prid=%08x pc=%08x status=%08x dpg=%08x\\n",')
    candidate = once(candidate,
        'RREG32_SOC15(UVD, 0, mmUVD_STATUS));\n\t\tdev_warn(adev->dev,\n'
        '\t\t\t "BC250 VCN direct reset released:',
        'RREG32_SOC15(UVD, 0, mmUVD_STATUS),\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_DPG_CLK_EN_VCPU_REPORT));\n'
        '\t\tdev_warn(adev->dev,\n'
        '\t\t\t "BC250 VCN direct reset released:')
    candidate = once(candidate,
        'BC250 VCPU clock wait0: gate=%08x cgcctrl=%08x cgc=%08x ctrl=%08x prid=%08x\\n",',
        'BC250 VCPU clock wait0: gate=%08x cgcctrl=%08x cgc=%08x ctrl=%08x prid=%08x dpg=%08x\\n",')
    candidate = once(candidate,
        'RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID));\n'
        '\t\tif (adev->pdev->device == 0x13fe && i == 0)\n'
        '\t\t\tdev_warn(adev->dev,\n'
        '\t\t\t\t "BC250 VCN VCPU wait0:',
        'RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),\n'
        '\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_DPG_CLK_EN_VCPU_REPORT));\n'
        '\t\tif (adev->pdev->device == 0x13fe && i == 0)\n'
        '\t\t\tdev_warn(adev->dev,\n'
        '\t\t\t\t "BC250 VCN VCPU wait0:')
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
