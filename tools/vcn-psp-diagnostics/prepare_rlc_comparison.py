#!/usr/bin/env python3
"""Generate a default-off RLC-versus-VCN signed-byte PSP control.

The two selectable candidates are always invalidated in private kernel memory.
This only emits source and a manifest; it does not touch the board or firmware.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / 'prepare_signature_control.py'
BASE_SHA = '4f70ff8ef86905ae93b19b204302809a7dbb4e2406bf6991999e3e7392886a47'
VCN_SOURCE_SHA = '5716148b49f51ef16568dcf2378519a99b4d79bff24d6a5da4de6b05f1d9f599'
RLC_FIRMWARE_SHA = '20acefdb6128a36275f4382425a109a7c9927f6053eab685bb51164ff1d18cfb'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'expected exactly one source anchor: {old[:80]!r}')
    return source.replace(old, new, 1)


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)


def generate(kernel_build):
    if sha(BASE.read_bytes()) != BASE_SHA:
        raise ValueError('signed-byte base generator changed')
    spec = importlib.util.spec_from_file_location('signature_base', BASE)
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    original = (kernel_build / 'psp-probe-original-amdgpu_psp.c').read_bytes()
    auth = (kernel_build / 'psp-auth-functions.c').read_bytes()
    initial = base.generate(original, auth)
    if sha(initial) != VCN_SOURCE_SHA:
        raise ValueError('pinned VCN diagnostic source changed')
    source = initial.decode()
    source = replace_once(source,
        '/* Signed-byte tamper only: no valid VCN load or decoder MMIO. */',
        '/* Signed-byte tamper controls only: no valid firmware load or decoder MMIO. */')
    source = replace_once(source,
        '\tstatic const u8 vcn_key[16] = {\n'
        '\t\t0xc3, 0x72, 0x90, 0xc3, 0x10, 0xe6, 0x4a, 0x62,\n'
        '\t\t0xb0, 0x27, 0xc5, 0x66, 0x95, 0x49, 0x23, 0x68,\n'
        '\t};\n',
        '\tstatic const u8 vcn_key[16] = {\n'
        '\t\t0xc3, 0x72, 0x90, 0xc3, 0x10, 0xe6, 0x4a, 0x62,\n'
        '\t\t0xb0, 0x27, 0xc5, 0x66, 0x95, 0x49, 0x23, 0x68,\n'
        '\t};\n'
        '\tstatic const u8 gfx_key[16] = {\n'
        '\t\t0x30, 0xb8, 0x86, 0x51, 0x25, 0x42, 0x44, 0x99,\n'
        '\t\t0xae, 0xff, 0x3a, 0xc3, 0x5c, 0xe6, 0x21, 0xa6,\n'
        '\t};\n')
    source = replace_once(source,
        'if (!bc250_vcn_psp_probe || value != 4 ||',
        'if (!bc250_vcn_psp_probe || (value != 4 && value != 5) ||')
    source = replace_once(source,
        '\tret = amdgpu_ucode_request(adev, &fw, AMDGPU_UCODE_REQUIRED,\n'
        '\t\t\t\t  "amdgpu/navi10_vcn.bin");',
        '\tret = amdgpu_ucode_request(adev, &fw, AMDGPU_UCODE_REQUIRED,\n'
        '\t\t\t\t  value == 4 ? "amdgpu/navi10_vcn.bin" :\n'
        '\t\t\t\t  "amdgpu/cyan_skillfish2_rlc.bin");')
    source = replace_once(source,
        '\tif (offset != 256 || size != 405696 ||\n'
        '\t    le32_to_cpu(header->ucode_version) != 0x0811800d ||\n'
        '\t    memcmp(fw->data + offset + 0x38, vcn_key, sizeof(vcn_key)) ||\n'
        '\t    get_unaligned_le32(fw->data + offset + 0x14) != 0x61380 ||\n'
        '\t    get_unaligned_le32(fw->data + offset + 0x70) != 0x1b40 ||\n'
        '\t    fw->data[offset + 0x7f]) {',
        '\tif (offset != 256 || size < 0x80 || fw->data[offset + 0x7f] ||\n'
        '\t    (value == 4 && (size != 405696 ||\n'
        '\t     le32_to_cpu(header->ucode_version) != 0x0811800d ||\n'
        '\t     memcmp(fw->data + offset + 0x38, vcn_key, sizeof(vcn_key)) ||\n'
        '\t     get_unaligned_le32(fw->data + offset + 0x14) != 0x61380 ||\n'
        '\t     get_unaligned_le32(fw->data + offset + 0x70) != 0x1b40)) ||\n'
        '\t    (value == 5 && (size != 25088 ||\n'
        '\t     le32_to_cpu(header->ucode_version) != 0x0000000d ||\n'
        '\t     memcmp(fw->data + offset + 0x38, gfx_key, sizeof(gfx_key)) ||\n'
        '\t     get_unaligned_le32(fw->data + offset + 0x14) != 0x6000 ||\n'
        '\t     get_unaligned_le32(fw->data + offset + 0x70) != 0))) {')
    source = replace_once(source,
        '\t/* Last signed byte: unchanged header/key/signature, invalid body. */\n'
        '\tpayload[0x6147f] ^= 1;',
        '\t/* Last signed byte: unchanged header/key/signature, invalid body. */\n'
        '\tpayload[value == 4 ? 0x6147f : 0x60ff] ^= 1;')
    source = replace_once(source,
        '\tcmd->cmd.cmd_load_ip_fw.fw_type = GFX_FW_TYPE_VCN;',
        '\tcmd->cmd.cmd_load_ip_fw.fw_type = value == 4 ? GFX_FW_TYPE_VCN :\n'
        '\t\t\t\t\t     GFX_FW_TYPE_RLC_G;')
    source = replace_once(source,
        '"BC250 VCN PSP auth: variant=%llu type=%u size=%u signed_byte_tampered=0x6147f\\n",\n'
        '\t\t value, GFX_FW_TYPE_VCN, size);',
        '"BC250 VCN PSP auth: variant=%llu type=%u size=%u signed_byte_tampered=0x%x\\n",\n'
        '\t\t value, cmd->cmd.cmd_load_ip_fw.fw_type, size,\n'
        '\t\t value == 4 ? 0x6147f : 0x60ff);')
    if source.count('payload[value == 4 ? 0x6147f : 0x60ff] ^= 1;') != 1:
        raise ValueError('required tamper not present')
    return source.encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    source = generate(args.kernel_build)
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_private(args.output_dir / 'amdgpu_psp.c', source)
    manifest = dict(source_sha256=sha(source), parent_sha256=VCN_SOURCE_SHA,
                    rlc_firmware_sha256=RLC_FIRMWARE_SHA,
                    variants={'4': {'type': 13, 'tamper_offset': '0x6147f'},
                              '5': {'type': 8, 'tamper_offset': '0x60ff'}},
                    valid_firmware_load_exposed=False, decoder_startup_enabled=False,
                    board_access=False, bios_flash_writes=False)
    write_private(args.output_dir / 'manifest.json',
                  (json.dumps(manifest, indent=2) + '\n').encode())
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
