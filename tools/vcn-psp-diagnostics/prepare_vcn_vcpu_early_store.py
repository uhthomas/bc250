#!/usr/bin/env python3
"""Trap the VCN VCPU immediately after its earliest visible bootstrap store.

Patch only the temporary direct-load GPU BO: change the value loaded by the
authentic store at payload offset 0x454, and replace its following instruction
with a self-loop. The store target is the firmware's own 0x6100ffd0 literal.
If the host sees the marker in the mapped stack BO, at least one VCPU store
instruction executed. A zero result does not prove the VCPU cannot execute.
"""

import hashlib
import json
import lzma
from pathlib import Path
import struct

import prepare_vcn_vcpu_marker_stub as marker
from prepare_vcn_vcpu_spin_stub import FIRMWARE, FIRMWARE_SHA


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-vcpu-marker-stub-20260929/amdgpu_vcn.c'
SOURCE_SHA = 'e68896b29a936d348828552e7d77feccd733bca76b5d29fd6bea92dc414a05af'
V2 = BUILD / 'vcn-vcpu-marker-stub-20260929/vcn_v2_0.c'
V2_SHA = '10690ebca77d95f8d8226aed9db106e2875cfed287a7c786857302cdf80b7b86'
DEST = BUILD / 'vcn-vcpu-early-store-20260929'
MARKER = 0x7bc25002
OLD_LITERAL = struct.pack('<I', 0x61010010)
OLD_NEXT = bytes.fromhex('3134ff')
SELF_LOOP = bytes.fromhex('06ffff')

EARLY_BLOCK = '''\t\t\t\t\tstatic const u8 old_literal[4] = {
\t\t\t\t\t\t0x10, 0x00, 0x01, 0x61
\t\t\t\t\t};
\t\t\t\t\tstatic const u8 old_next[3] = { 0x31, 0x34, 0xff };
\t\t\t\t\tstatic const u8 marker[4] = { 0x02, 0x50, 0xc2, 0x7b };
\t\t\t\t\tstatic const u8 loop[3] = { 0x06, 0xff, 0xff };
\t\t\t\t\tu8 check_literal[4], check_next[3];

\t\t\t\t\tmemcpy_fromio(check_literal,
\t\t\t\t\t\t      adev->vcn.inst[i].cpu_addr + 0x124,
\t\t\t\t\t\t      sizeof(check_literal));
\t\t\t\t\tmemcpy_fromio(check_next,
\t\t\t\t\t\t\t      adev->vcn.inst[i].cpu_addr + 0x456,
\t\t\t\t\t\t\t      sizeof(check_next));
\t\t\t\t\tif (memcmp(check_literal, old_literal, sizeof(old_literal)) ||
\t\t\t\t\t    memcmp(check_next, old_next, sizeof(old_next))) {
\t\t\t\t\t\tdrm_dev_exit(idx);
\t\t\t\t\t\tdev_err(adev->dev, "BC250 VCPU early source guard failed\\n");
\t\t\t\t\t\treturn -EINVAL;
\t\t\t\t\t}
\t\t\t\t\tmemcpy_toio(adev->vcn.inst[i].cpu_addr + 0x124,
\t\t\t\t\t\t    marker, sizeof(marker));
\t\t\t\t\tmemcpy_toio(adev->vcn.inst[i].cpu_addr + 0x456,
\t\t\t\t\t\t    loop, sizeof(loop));
\t\t\t\t\tmemcpy_fromio(check_literal,
\t\t\t\t\t\t      adev->vcn.inst[i].cpu_addr + 0x124,
\t\t\t\t\t\t      sizeof(check_literal));
\t\t\t\t\tmemcpy_fromio(check_next,
\t\t\t\t\t\t\t      adev->vcn.inst[i].cpu_addr + 0x456,
\t\t\t\t\t\t      sizeof(check_next));
\t\t\t\t\tif (memcmp(check_literal, marker, sizeof(marker)) ||
\t\t\t\t\t    memcmp(check_next, loop, sizeof(loop))) {
\t\t\t\t\t\tdrm_dev_exit(idx);
\t\t\t\t\t\tdev_err(adev->dev, "BC250 VCPU early BO readback failed\\n");
\t\t\t\t\t\treturn -EIO;
\t\t\t\t\t}
\t\t\t\t\tdev_warn(adev->dev,
\t\t\t\t\t\t "BC250 VCPU early BO: store=454 next=456 bytes=%02x%02x%02x literal=124 value=%02x%02x%02x%02x target=6100ffd0\\n",
\t\t\t\t\t\t check_next[0], check_next[1], check_next[2],
\t\t\t\t\t\t check_literal[0], check_literal[1],
\t\t\t\t\t\t check_literal[2], check_literal[3]);
'''


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    vcn = SOURCE.read_bytes()
    v2 = V2.read_bytes()
    firmware = lzma.decompress(FIRMWARE.read_bytes())
    if (sha(vcn) != SOURCE_SHA or sha(v2) != V2_SHA or
            sha(firmware) != FIRMWARE_SHA or
            firmware[0x224:0x228] != OLD_LITERAL or
            firmware[0x554:0x556] != bytes.fromhex('3902') or
            firmware[0x556:0x559] != OLD_NEXT or
            firmware[0xf41b:0xf41e] != SELF_LOOP):
        raise ValueError('pinned VCPU early-store sources changed')
    body = marker.once(vcn.decode(), marker.NEW, EARLY_BLOCK)
    other = v2.decode()
    for old, new in (
        ('BC250 VCPU marker before:', 'BC250 VCPU early before:'),
        ('BC250 VCPU marker after:', 'BC250 VCPU early after:'),
        ('BC250 VCPU marker wait0:', 'BC250 VCPU early wait0:'),
    ):
        other = marker.once(other, old, new)
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in (('amdgpu_vcn.c', body.encode()),
                       ('vcn_v2_0.c', other.encode())):
        path = DEST / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_bytes(data)
    report = {
        'firmware_sha256': FIRMWARE_SHA,
        'authentic_store_buffer_offset': '0x454',
        'literal_buffer_offset': '0x124',
        'following_instruction_buffer_offset': '0x456',
        'following_instruction_bytes': SELF_LOOP.hex(),
        'marker': hex(MARKER),
        'host_stack_buffer_offset': '0x73fd0',
        'scope': 'temporary GPU buffer only; installed firmware and EEPROM unchanged',
        'stack_address_mapping_is_hypothesis': True,
        'sources': {'amdgpu_vcn.c': sha(body.encode()),
                    'vcn_v2_0.c': sha(other.encode())},
    }
    (DEST / 'early-store.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
