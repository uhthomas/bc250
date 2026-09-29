#!/usr/bin/env python3
"""Sample the powered VCN free counter around a guarded VCPU clock toggle."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "output/video-decode-20260922/kernel-build"
SOURCE = BUILD / "vcn-vcpu-clock-readback-20260928/vcn_v2_0.c"
DEST = BUILD / "vcn-free-counter-20260928/vcn_v2_0.c"
SOURCE_SHA = "320c3bcb5b5997ffc8e1c870dae61c8d19f0003f0b412fd6fed34bfdd467369b"

OLD = '''\t\t\tu32 cleared, restored;

\t\t\tWREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL,
\t\t\t\t       before & ~UVD_VCPU_CNTL__CLK_EN_MASK);
\t\t\tudelay(10);
\t\t\tcleared = RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL);
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL, before);
\t\t\trestored = RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN VCPU clock readback: before=%08x cleared=%08x restored=%08x\\n",
\t\t\t\t before, cleared, restored);
'''

NEW = '''\t\t\tu32 cleared, restored;
\t\t\tu32 free_before, free_enabled, free_disabled, free_restored;

\t\t\tfree_before = RREG32_SOC15(UVD, 0, mmUVD_FREE_COUNTER_REG);
\t\t\tudelay(100);
\t\t\tfree_enabled = RREG32_SOC15(UVD, 0, mmUVD_FREE_COUNTER_REG);
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL,
\t\t\t\t       before & ~UVD_VCPU_CNTL__CLK_EN_MASK);
\t\t\tudelay(100);
\t\t\tcleared = RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL);
\t\t\tfree_disabled = RREG32_SOC15(UVD, 0, mmUVD_FREE_COUNTER_REG);
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL, before);
\t\t\tudelay(100);
\t\t\trestored = RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL);
\t\t\tfree_restored = RREG32_SOC15(UVD, 0, mmUVD_FREE_COUNTER_REG);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN VCPU clock readback: before=%08x cleared=%08x restored=%08x\\n",
\t\t\t\t before, cleared, restored);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN free counter: before=%08x enabled=%08x disabled=%08x restored=%08x\\n",
\t\t\t\t free_before, free_enabled, free_disabled, free_restored);
'''


def main():
    source_bytes = SOURCE.read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest() == SOURCE_SHA
    source = source_bytes.decode()
    assert source.count(OLD) == 1
    source = source.replace(OLD, NEW, 1)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST)
    print(hashlib.sha256(source.encode()).hexdigest())


if __name__ == "__main__":
    main()
