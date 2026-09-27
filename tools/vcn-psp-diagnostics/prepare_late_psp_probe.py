#!/usr/bin/env python3
"""Add the existing default-off VCN load debugfs hook to the pinned PSP source."""
import argparse
import hashlib
import json
import os
from pathlib import Path

BASE_SHA = '7710ae058d9dbcbee8dfef2273c825565e284cbd8ed39d125f7ef5f1a42624f4'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(data, old, new):
    if data.count(old) != 1:
        raise ValueError(f'Expected one source anchor: {old[:65]!r}')
    return data.replace(old, new, 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel-build', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    a = ap.parse_args()
    path = a.kernel_build / 'linux-7.2.5/drivers/gpu/drm/amd/amdgpu/amdgpu_psp.c'
    source = path.read_bytes()
    if sha(source) != BASE_SHA:
        raise ValueError('Pinned PSP source changed')
    functions = (a.kernel_build / 'psp-probe-functions.c').read_bytes()
    source = replace_once(source,
        b'#define AMD_VBIOS_FILE_MAX_SIZE_B      (1024*1024*16)\n',
        b'#define AMD_VBIOS_FILE_MAX_SIZE_B      (1024*1024*16)\n\n'
        b'static bool bc250_vcn_psp_probe;\n'
        b'module_param_named(bc250_vcn_psp_probe, bc250_vcn_psp_probe, bool, 0444);\n'
        b'MODULE_PARM_DESC(bc250_vcn_psp_probe,\n'
        b'\t\t"Expose BC250 VCN PSP load probe (default off)");\n')
    source = replace_once(source,
        b'static int psp_read_spirom_debugfs_open',
        functions + b'\nstatic int psp_read_spirom_debugfs_open')
    source = replace_once(source,
        b'\tstruct drm_minor *minor = adev_to_drm(adev)->primary;\n',
        b'\tstruct drm_minor *minor = adev_to_drm(adev)->primary;\n\n'
        b'\tif (bc250_vcn_psp_probe &&\n'
        b'\t    adev->asic_type == CHIP_CYAN_SKILLFISH &&\n'
        b'\t    adev->pdev->device == 0x13fe &&\n'
        b'\t    amdgpu_ip_version(adev, VCN_HWIP, 0) == IP_VERSION(2, 0, 3))\n'
        b'\t\tdebugfs_create_file("bc250_vcn_psp_load", 0200,\n'
        b'\t\t\t\t    minor->debugfs_root, adev,\n'
        b'\t\t\t\t    &bc250_vcn_psp_probe_fops);\n')
    a.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {'base_sha256': BASE_SHA, 'source_sha256': sha(source),
                'probe_functions_sha256': sha(functions),
                'vcn_probe_default_off': True, 'bios_flash_writes': False,
                'hardware_decode_verified': False}
    for name, data in (('amdgpu_psp.c', source),
                       ('manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())):
        fd = os.open(a.output_dir / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
