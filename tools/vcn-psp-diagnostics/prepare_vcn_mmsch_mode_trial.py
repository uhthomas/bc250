#!/usr/bin/env python3
"""Clear one VCN MMSCH clock mode bit before guarded static VCPU startup.

This is an opt-in, volatile diagnostic trial. The observed CGC_CTRL has
MMSCH_MODE=1 even though CC_UVD_HARVESTING reports MMSCH_DISABLE=1. The
experiment tests whether that contradictory mode blocks the static VCPU path.
It does not change the BIOS or the signed PSP/Pico profile.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-memory-requests-20260929/vcn_v2_0.c'
SOURCE_SHA = '26b58c21fa8e695d0e5356902a19f48d22b186995a962efa3bb53b81078b51a3'
DEST = BUILD / 'vcn-mmsch-mode-20260929'
PRE = '\t/* On this BC250 UVD_SOFT_RESET reads as all ones. Avoid carrying\n'
POST = '\tfor (i = 0; i < 10; ++i) {\n'


def main() -> None:
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('pinned LMI source changed')
    source = data.decode()
    for name, anchor in (('pre', PRE), ('post', POST)):
        if source.count(anchor) != 1:
            raise ValueError(f'{name} anchor changed')
    pre = '''\tif (adev->pdev->device == 0x13fe) {
\t\tu32 power = RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS);
\t\tu32 pgfsm = RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS);
\t\tu32 version = RREG32_SOC15(UVD, 0, mmUVD_VERSION);
\t\tu32 harvest = RREG32_SOC15(UVD, 0, mmCC_UVD_HARVESTING);
\t\tu32 before = RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL);
\t\tu32 gate = RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE);
\t\tu32 vcpu = RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL);
\t\tu32 candidate = before & ~UVD_CGC_CTRL__MMSCH_MODE_MASK;
\t\tu32 after;

\t\t/* Only change the precisely measured static-startup state. */
\t\tif (power != 0x800 || pgfsm != 0 || version != 0x2001b ||
\t\t    harvest != 3 || before != 0x8000018c ||
\t\t    gate != 0x00100000 || vcpu != 0x0ff20200) {
\t\t\tdev_err(adev->dev,
\t\t\t\t "BC250 MMSCH mode guard failed: power=%08x pgfsm=%08x version=%08x harvest=%08x ctrl=%08x gate=%08x vcpu=%08x\\n",
\t\t\t\t power, pgfsm, version, harvest, before, gate, vcpu);
\t\t\treturn -EINVAL;
\t\t}
\t\tWREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL, candidate);
\t\tafter = RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 MMSCH mode pre: before=%08x candidate=%08x after=%08x status=%08x reset2=%08x report=%08x lmi=%08x\\n",
\t\t\t before, candidate, after,
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET2),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_DPG_CLK_EN_VCPU_REPORT),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_STATUS));
\t\tif (after != candidate) {
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL, before);
\t\t\treturn -EIO;
\t\t}
\t}

'''
    post = '''\tif (adev->pdev->device == 0x13fe)
\t\tdev_warn(adev->dev,
\t\t\t "BC250 MMSCH mode release: ctrl=%08x status=%08x reset2=%08x report=%08x lmi=%08x uvd=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET2),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_DPG_CLK_EN_VCPU_REPORT),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS));

'''
    source = source.replace(PRE, pre + PRE, 1)
    source = source.replace(POST, post + POST, 1)
    DEST.mkdir(parents=True, exist_ok=True)
    vcn = BUILD / 'vcn-memory-requests-20260929/amdgpu_vcn.c'
    if hashlib.sha256(vcn.read_bytes()).hexdigest() != (
            '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'):
        raise ValueError('pinned amdgpu_vcn.c changed')
    for name, contents in (('vcn_v2_0.c', source),
                           ('amdgpu_vcn.c', vcn.read_text())):
        path = DEST / name
        if path.exists() and path.read_text() != contents:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_text(contents)
        print(name, hashlib.sha256(contents.encode()).hexdigest())


if __name__ == '__main__':
    main()
