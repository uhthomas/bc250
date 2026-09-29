#!/usr/bin/env python3
"""Put a write-and-loop Xtensa canary in the temporary VCN direct-load BO.

The installed firmware is used only for its verified metadata and surrounding
image layout. The 12-byte instruction stream and two literals are replaced in
the BO, not on disk. An RBC reset pulse then gives the VCPU a bounded chance
to write a marker at its inferred 0x6100ffd0 stack address. Host readback
of BO offset 0x73fd0 is the positive witness; a negative result remains
ambiguous if that VCPU address or code entry is wrong.
"""

import hashlib
import json
from pathlib import Path
import struct


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-vcpu-spin-stub-20260929/amdgpu_vcn.c'
SOURCE_SHA = 'b96c3f99ecd10ee607b256a2b0608bd10dacbc4f008f9f4820c8a8c9616963ef'
V2 = BUILD / 'vcn-vcpu-spin-ring-reset-20260929/vcn_v2_0.c'
V2_SHA = '904b8672d8fcb695a8547e00412f117add9771102fa9690985761a5a5a338081'
DEST = BUILD / 'vcn-vcpu-marker-stub-20260929'
PROGRAM = bytes.fromhex('21fefb31fefb32620006ffff')
ADDRESS = 0x6100ffd0
MARKER = 0x7bc25001
EARLY_BOOT_VALUE = 0x61010010

OLD = '''\t\t\t\t\tstatic const u8 spin[3] = { 0x06, 0xff, 0xff };
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
'''

NEW = '''\t\t\t\t\tstatic const u8 program[12] = {
\t\t\t\t\t\t0x21, 0xfe, 0xfb, 0x31, 0xfe, 0xfb,
\t\t\t\t\t\t0x32, 0x62, 0x00, 0x06, 0xff, 0xff
\t\t\t\t\t};
\t\t\t\t\tstatic const u8 literals[8] = {
\t\t\t\t\t\t0xd0, 0xff, 0x00, 0x61,
\t\t\t\t\t\t0x01, 0x50, 0xc2, 0x7b
\t\t\t\t\t};
\t\t\t\t\tu8 check_program[12], check_literals[8];

\t\t\t\t\tmemcpy_toio(adev->vcn.inst[i].cpu_addr + 0xe200,
\t\t\t\t\t\t    literals, sizeof(literals));
\t\t\t\t\tmemcpy_toio(adev->vcn.inst[i].cpu_addr + 0xf208,
\t\t\t\t\t\t    program, sizeof(program));
\t\t\t\t\tmemcpy_fromio(check_literals,
\t\t\t\t\t\t      adev->vcn.inst[i].cpu_addr + 0xe200,
\t\t\t\t\t\t      sizeof(check_literals));
\t\t\t\t\tmemcpy_fromio(check_program,
\t\t\t\t\t\t      adev->vcn.inst[i].cpu_addr + 0xf208,
\t\t\t\t\t\t      sizeof(check_program));
\t\t\t\t\tif (memcmp(check_literals, literals, sizeof(literals)) ||
\t\t\t\t\t    memcmp(check_program, program, sizeof(program))) {
\t\t\t\t\t\tdrm_dev_exit(idx);
\t\t\t\t\t\tdev_err(adev->dev, "BC250 VCPU marker BO readback failed\\n");
\t\t\t\t\t\treturn -EIO;
\t\t\t\t\t}
\t\t\t\t\tdev_warn(adev->dev,
\t\t\t\t\t\t "BC250 VCPU marker BO: code=f208 bytes=%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x address=%08x value=%08x\\n",
\t\t\t\t\t\t check_program[0], check_program[1], check_program[2],
\t\t\t\t\t\t check_program[3], check_program[4], check_program[5],
\t\t\t\t\t\t check_program[6], check_program[7], check_program[8],
\t\t\t\t\t\t check_program[9], check_program[10], check_program[11],
\t\t\t\t\t\t 0x6100ffd0, 0x7bc25001);
'''


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'VCN marker anchor changed: {old[:80]!r}')
    return source.replace(old, new, 1)


def main() -> None:
    source = SOURCE.read_bytes()
    v2 = V2.read_bytes()
    if sha(source) != SOURCE_SHA or sha(v2) != V2_SHA:
        raise ValueError('pinned VCPU marker sources changed')
    body = once(source.decode(), OLD, NEW)
    body = body.replace('BC250 VCPU spin source guard failed',
                        'BC250 VCPU marker source guard failed')
    other = v2.decode()
    other = once(other,
        '\t\tu32 rptr_changes = 0, lmi_changes = 0;\n',
        '\t\tu32 rptr_changes = 0, lmi_changes = 0;\n'
        '\t\tu32 marker_before, marker_after;\n')
    other = once(other,
        '\t\t/* A successful SCRATCH9 packet established that 0xc000-prefixed\n',
        '\t\tmemcpy_fromio(&marker_before,\n'
        '\t\t\tadev->vcn.inst[0].cpu_addr + 0x73fd0, sizeof(marker_before));\n'
        '\t\tdev_warn(adev->dev, "BC250 VCPU marker before: value=%08x\\n",\n'
        '\t\t\t marker_before);\n'
        '\t\t/* A successful SCRATCH9 packet established that 0xc000-prefixed\n')
    other = once(other,
        '\n\t\tif (RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != 0x0ff20200) {',
        '\n\t\tmemcpy_fromio(&marker_after,\n'
        '\t\t\tadev->vcn.inst[0].cpu_addr + 0x73fd0, sizeof(marker_after));\n'
        '\t\tdev_warn(adev->dev,\n'
        '\t\t\t "BC250 VCPU marker after: value=%08x before=%08x pc=%08x\\n",\n'
        '\t\t\t marker_after, marker_before,\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE));\n'
        '\n\t\tif (RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != 0x0ff20200) {')
    other = once(other,
        '\t\tif (adev->pdev->device == 0x13fe && i == 0)\n'
        '\t\t\tdev_warn(adev->dev,\n'
        '\t\t\t\t "BC250 VCN LMI monitor wait0:',
        '\t\tif (adev->pdev->device == 0x13fe && i == 0) {\n'
        '\t\t\tu32 marker_wait;\n'
        '\t\t\tmemcpy_fromio(&marker_wait,\n'
        '\t\t\t\tadev->vcn.inst[0].cpu_addr + 0x73fd0,\n'
        '\t\t\t\tsizeof(marker_wait));\n'
        '\t\t\tdev_warn(adev->dev,\n'
        '\t\t\t\t "BC250 VCPU marker wait0: value=%08x\\n",\n'
        '\t\t\t\t marker_wait);\n'
        '\t\t}\n'
        '\t\tif (adev->pdev->device == 0x13fe && i == 0)\n'
        '\t\t\tdev_warn(adev->dev,\n'
        '\t\t\t\t "BC250 VCN LMI monitor wait0:')
    if struct.pack('<II', ADDRESS, MARKER) != bytes.fromhex('d0ff00610150c27b'):
        raise AssertionError('Xtensa literal bytes changed')
    from prepare_vcn_vcpu_spin_stub import FIRMWARE, FIRMWARE_SHA
    import lzma
    firmware = lzma.decompress(FIRMWARE.read_bytes())
    if sha(firmware) != FIRMWARE_SHA or \
            struct.unpack_from('<II', firmware, 0x220) != \
            (ADDRESS, EARLY_BOOT_VALUE):
        raise ValueError('pinned early VCPU stack-store literals changed')
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in (('amdgpu_vcn.c', body.encode()),
                       ('vcn_v2_0.c', other.encode())):
        path = DEST / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_bytes(data)
    report = {
        'program': PROGRAM.hex(),
        'disassembly': ['l32r a2,0xe200', 'l32r a3,0xe204',
                        's32i a3,a2,0', 'j 0xf211'],
        'literal_address': hex(ADDRESS),
        'literal_marker': hex(MARKER),
        'code_buffer_offset': '0xf208',
        'literal_buffer_offset': '0xe200',
        'host_marker_buffer_offset': '0x73fd0',
        'early_boot_store_value': hex(EARLY_BOOT_VALUE),
        'entry_and_address_are_hypotheses': True,
        'installed_firmware_unchanged': True,
        'sources': {'amdgpu_vcn.c': sha(body.encode()),
                    'vcn_v2_0.c': sha(other.encode())},
    }
    (DEST / 'marker-stub.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
