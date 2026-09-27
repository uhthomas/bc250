#!/usr/bin/env python3
"""Prepare a default-off BC250 VCN driver that keeps normal PSP loading."""
import argparse
import hashlib
import json
import os
from pathlib import Path

BASE_SHA = '8390fdcdc7b258507f9954ead0e3635f6eae5dfc954c28fa1b5240fc32a88bf9'
OLD = (b'\treturn adev->firmware.load_type == AMDGPU_FW_LOAD_PSP &&\n'
       b'\t\t!amdgpu_vcn_bc250_experimental(adev);')
NEW = b'\treturn adev->firmware.load_type == AMDGPU_FW_LOAD_PSP;'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    source = (args.kernel_build / 'linux-7.2.5/drivers/gpu/drm/amd/amdgpu/amdgpu_vcn.c').read_bytes()
    if sha(source) != BASE_SHA or source.count(OLD) != 1:
        raise ValueError('Pinned VCN source changed')
    changed = source.replace(OLD, NEW, 1)
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, data in (
        ('amdgpu_vcn.c', changed),
        ('manifest.json', (json.dumps({
            'base_sha256': BASE_SHA, 'source_sha256': sha(changed),
            'bc250_vcn_default_off': True, 'load_type': 'PSP',
            'bios_flash_writes': False, 'hardware_decode_verified': False,
        }, indent=2) + '\n').encode()),
    ):
        fd = os.open(args.output_dir / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
    print((args.output_dir / 'manifest.json').read_text())


if __name__ == '__main__':
    main()
