#!/usr/bin/env python3
"""Build a RAM-only direct-BO VCPU spin-stub trial for the BC250.

The installed, pinned VCN firmware is never changed. Its first plausible
Xtensa bootstrap prologue at file offset 0xf308 is replaced only in the VCPU
buffer with the self-loop instruction already present in that same firmware.
This probes instruction fetch; it cannot make the VCPU leave reset.
"""

import hashlib
import json
import lzma
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-direct-bo-powered-20260928/amdgpu_vcn.c'
SOURCE_SHA = '971c2f10e199bd51a749ac0083b411ffb24bb3e85daf8637038b64900078b7a3'
V2 = BUILD / 'vcn-direct-bo-powered-20260928/vcn_v2_0.c'
V2_SHA = '68078fd630e42b37964f4c56614617000b2b1bd163210c30904b950180291644'
FIRMWARE = ROOT / 'output/video-decode-20260922/psp-analysis/navi10_vcn.bin.xz'
FIRMWARE_SHA = 'a9ec155695b5020009d3986cfd4ebd00ad9ddbd12ac7e5fa15ec86b8a571dbe5'
DEST = BUILD / 'vcn-vcpu-spin-stub-20260929'
FILE_OFFSET = 0xf308
PAYLOAD_OFFSET = FILE_OFFSET - 0x100
OLD = bytes.fromhex('36e100')
SPIN = bytes.fromhex('06ffff')

ANCHOR = '''\t\t\toffset = le32_to_cpu(hdr->ucode_array_offset_bytes);
\t\t\tif (drm_dev_enter(adev_to_drm(adev), &idx)) {
\t\t\t\tmemcpy_toio(adev->vcn.inst[i].cpu_addr,
\t\t\t\t\t    adev->vcn.inst[i].fw->data + offset,
\t\t\t\t\t    le32_to_cpu(hdr->ucode_size_bytes));
\t\t\t\tdrm_dev_exit(idx);
\t\t\t}
'''

REPLACEMENT = '''\t\t\toffset = le32_to_cpu(hdr->ucode_array_offset_bytes);
\t\t\tif (adev->pdev->device == 0x13fe && i == 0 &&
\t\t\t    (adev->vcn.inst[i].fw->size != 405952 || offset != 0x100 ||
\t\t\t     le32_to_cpu(hdr->ucode_size_bytes) != 0x630c0 ||
\t\t\t     memcmp(adev->vcn.inst[i].fw->data + 0xf308,
\t\t\t\t    "\\x36\\xe1\\x00", 3))) {
\t\t\t\tdev_err(adev->dev, "BC250 VCPU spin source guard failed\\n");
\t\t\t\treturn -EINVAL;
\t\t\t}
\t\t\tif (drm_dev_enter(adev_to_drm(adev), &idx)) {
\t\t\t\tmemcpy_toio(adev->vcn.inst[i].cpu_addr,
\t\t\t\t\t    adev->vcn.inst[i].fw->data + offset,
\t\t\t\t\t    le32_to_cpu(hdr->ucode_size_bytes));
\t\t\t\tif (adev->pdev->device == 0x13fe && i == 0) {
\t\t\t\t\tstatic const u8 spin[3] = { 0x06, 0xff, 0xff };
\t\t\t\t\tu8 check[3];

\t\t\t\t\tmemcpy_toio(adev->vcn.inst[i].cpu_addr + 0xf208,
\t\t\t\t\t\t    spin, sizeof(spin));
\t\t\t\t\tmemcpy_fromio(check,
\t\t\t\t\t\t      adev->vcn.inst[i].cpu_addr + 0xf208,
\t\t\t\t\t\t      sizeof(check));
\t\t\t\t\tif (memcmp(check, spin, sizeof(spin))) {
\t\t\t\t\t\tdrm_dev_exit(idx);
\t\t\t\t\t\tdev_err(adev->dev, "BC250 VCPU spin BO readback failed\\n");
\t\t\t\t\t\treturn -EIO;
\t\t\t\t\t}
\t\t\t\t\tdev_warn(adev->dev,
\t\t\t\t\t\t "BC250 VCPU spin BO: file=f308 buffer=f208 bytes=%02x%02x%02x\\n",
\t\t\t\t\t\t check[0], check[1], check[2]);
\t\t\t\t}
\t\t\t\tdrm_dev_exit(idx);
\t\t\t}
'''


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    source = SOURCE.read_bytes()
    v2 = V2.read_bytes()
    firmware = lzma.decompress(FIRMWARE.read_bytes())
    if sha(source) != SOURCE_SHA or sha(v2) != V2_SHA or sha(firmware) != FIRMWARE_SHA:
        raise ValueError('pinned direct-load sources changed')
    if (len(firmware) != 405952 or firmware[FILE_OFFSET:FILE_OFFSET + 3] != OLD or
            firmware[0xf41b:0xf41e] != SPIN or
            int.from_bytes(firmware[0x14:0x18], 'little') != 0x630c0 or
            int.from_bytes(firmware[0x18:0x1c], 'little') != 0x100):
        raise ValueError('VCN bootstrap or self-loop evidence changed')
    body = source.decode()
    if body.count(ANCHOR) != 1:
        raise ValueError('direct BO copy site changed')
    candidate = body.replace(ANCHOR, REPLACEMENT).encode()
    DEST.mkdir(parents=True, exist_ok=True)
    for name, content in (('amdgpu_vcn.c', candidate), ('vcn_v2_0.c', v2)):
        path = DEST / name
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_bytes(content)
    report = {
        'source_firmware_sha256': FIRMWARE_SHA,
        'candidate_source_sha256': sha(candidate),
        'file_offset': hex(FILE_OFFSET),
        'direct_bo_offset': hex(PAYLOAD_OFFSET),
        'old_bytes': OLD.hex(),
        'program_bytes': SPIN.hex(),
        'authentic_self_loop_file_offset': '0xf41b',
        'hypothesis': '0xf308 is the VCPU bootstrap entry',
        'scope': 'temporary VCPU BO on opt-in diagnostic module; no installed firmware or EEPROM write',
        'negative_result_limit': 'A flat PC does not distinguish reset, wrong entry point or blocked fetch.',
    }
    (DEST / 'spin-stub.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
