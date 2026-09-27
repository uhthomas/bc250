#!/usr/bin/env python3
"""Add an invalid type-19 VCN-payload control to the guarded PSP probe."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / 'prepare_rlc_comparison.py'
BASE_SHA = 'aed2df715984260bac7e52215e752a4dac2dcfaa24dbf3869a52465901f92fc9'
BASE_SOURCE_SHA = '0fd339a8474e543db3bec94080a7d2a727a8f68d413be63f1089878ca312d3d5'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'expected exactly one source anchor: {old[:80]!r}')
    return source.replace(old, new, 1)


def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)


def generate(kernel_build):
    if sha(BASE.read_bytes()) != BASE_SHA:
        raise ValueError('RLC comparison generator changed')
    spec = importlib.util.spec_from_file_location('rlc_base', BASE)
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    initial = base.generate(kernel_build)
    if sha(initial) != BASE_SOURCE_SHA:
        raise ValueError('pinned RLC comparison source changed')
    source = initial.decode()
    source = replace_once(source,
        '(value != 4 && value != 5)',
        '(value != 4 && value != 5 && value != 6)')
    source = replace_once(source,
        'value == 4 ? "amdgpu/navi10_vcn.bin" :',
        '(value == 4 || value == 6) ? "amdgpu/navi10_vcn.bin" :')
    source = replace_once(source,
        '(value == 4 && (size != 405696 ||',
        '((value == 4 || value == 6) && (size != 405696 ||')
    source = replace_once(source,
        'payload[value == 4 ? 0x6147f : 0x60ff] ^= 1;',
        'payload[(value == 4 || value == 6) ? 0x6147f : 0x60ff] ^= 1;')
    source = replace_once(source,
        'cmd->cmd.cmd_load_ip_fw.fw_type = value == 4 ? GFX_FW_TYPE_VCN :\n'
        '\t\t\t\t\t     GFX_FW_TYPE_RLC_G;',
        'cmd->cmd.cmd_load_ip_fw.fw_type = value == 6 ? GFX_FW_TYPE_MMSCH :\n'
        '\t\t\t\t(value == 4 ? GFX_FW_TYPE_VCN : GFX_FW_TYPE_RLC_G);')
    source = replace_once(source,
        'value == 4 ? 0x6147f : 0x60ff);',
        '(value == 4 || value == 6) ? 0x6147f : 0x60ff);')
    if source.count('payload[(value == 4 || value == 6) ? 0x6147f : 0x60ff] ^= 1;') != 1:
        raise ValueError('required signed-byte tamper missing')
    return source.encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    source = generate(args.kernel_build)
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    private_write(args.output_dir / 'amdgpu_psp.c', source)
    manifest = dict(source_sha256=sha(source), base_source_sha256=BASE_SOURCE_SHA,
                    variants={'4': {'fw_type': 13, 'tamper': '0x6147f'},
                              '5': {'fw_type': 8, 'tamper': '0x60ff'},
                              '6': {'fw_type': 19, 'tamper': '0x6147f'}},
                    valid_firmware_load_exposed=False, decoder_startup_enabled=False,
                    board_access=False, bios_flash_writes=False)
    private_write(args.output_dir / 'manifest.json',
                  (json.dumps(manifest, indent=2) + '\n').encode())
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
