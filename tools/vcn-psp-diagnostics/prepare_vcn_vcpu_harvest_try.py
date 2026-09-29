#!/usr/bin/env python3
"""Try clearing the powered VCN harvest indication for one volatile boot.

The candidate inherits the early-bootstrap store marker. It writes only the
powered VCN register, never BIOS/Pico flash, and the guarded runner cold-cycles
the board after the test. Readback determines whether the indication is a
software-writable latch; the marker determines whether early VCPU code ran.
"""

import hashlib
import json
from pathlib import Path

import prepare_vcn_vcpu_marker_stub as marker


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-vcpu-early-store-20260929/vcn_v2_0.c'
SOURCE_SHA = '6424bb912636278045ff3ae9dd794decf46a6def64d161c1a9d14a966db804d2'
VCN = BUILD / 'vcn-vcpu-early-store-20260929/amdgpu_vcn.c'
VCN_SHA = '1799c7dc4b12df0371e61d5741d6610ba5ac1ebdef4bbb015c7b36922bf83078'
DEST = BUILD / 'vcn-vcpu-harvest-try-20260929'

ANCHOR = '''\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCN direct reset before: reset=%08x status=%08x\\n",
'''
PROBE = '''\t\tWREG32_SOC15(UVD, 0, mmCC_UVD_HARVESTING, 0);
\t\tdev_warn(adev->dev,
\t\t\t "BC250 VCPU harvest trial: before=%08x after=%08x version=%08x\\n",
\t\t\t harvest,
\t\t\t RREG32_SOC15(UVD, 0, mmCC_UVD_HARVESTING),
\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VERSION));
'''


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    vcn, source = VCN.read_bytes(), SOURCE.read_bytes()
    if sha(vcn) != VCN_SHA or sha(source) != SOURCE_SHA:
        raise ValueError('pinned VCPU harvest candidate sources changed')
    body = marker.once(source.decode(), ANCHOR, PROBE + ANCHOR)
    body = marker.once(body,
        '\t\t    harvest != 3 || status != 4 || old_cntl != 0x01000101 ||',
        '\t\t    (harvest != 0 && harvest != 3) || status != 4 ||\n'
        '\t\t    old_cntl != 0x01000101 ||')
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in (('amdgpu_vcn.c', vcn), ('vcn_v2_0.c', body.encode())):
        path = DEST / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_bytes(data)
    report = {
        'volatile_register': 'CC_UVD_HARVESTING',
        'guarded_before': '0x00000003',
        'trial_write': '0x00000000',
        'early_store_marker': '0x7bc25002',
        'scope': 'one diagnostic boot only; no BIOS EEPROM or Pico QSPI write',
        'sources': {'amdgpu_vcn.c': sha(vcn),
                    'vcn_v2_0.c': sha(body.encode())},
    }
    (DEST / 'harvest-try.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
