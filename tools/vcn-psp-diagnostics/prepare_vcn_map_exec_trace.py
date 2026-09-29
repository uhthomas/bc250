#!/usr/bin/env python3
"""Add VCPU execution samples to the pinned, guarded PSP map trial."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-map-guard-20260927/vcn_v2_0.c'
DEST = BUILD / 'vcn-map-exec-trace-20260927/vcn_v2_0.c'
SOURCE_SHA = 'f58cbe9a6ffc5a782e3ece5c6db98afb2941b2ae571c1bc2b3f0601103147d46'
RELEASE_ANCHOR = '\tfor (i = 0; i < 10; ++i) {\n'
WAIT_ANCHOR = '\t\tr = 0;\n\t\tif (status & 2)\n'

RELEASE_TRACE = '''\tif (adev->pdev->device == 0x13fe)
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN VCPU release: pc=%08x pf=%08x latency=%08x\\n",
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CNTR));

'''
WAIT_TRACE = '''\t\tif (adev->pdev->device == 0x13fe && i == 0)
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCN VCPU wait0: pc=%08x pf=%08x latency=%08x\\n",
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CNTR));
'''


def main():
    data = SOURCE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA
    source = data.decode()
    assert source.count(RELEASE_ANCHOR) == 1
    assert source.count(WAIT_ANCHOR) == 1
    source = source.replace(RELEASE_ANCHOR, RELEASE_TRACE + RELEASE_ANCHOR, 1)
    source = source.replace(WAIT_ANCHOR, WAIT_TRACE + WAIT_ANCHOR, 1)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST)
    print(hashlib.sha256(source.encode()).hexdigest())


if __name__ == '__main__':
    main()
