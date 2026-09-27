#!/usr/bin/env python3
"""Compare invalid VCN payloads as PSP types 19 and 13 on one boot."""
import argparse
import errno
import hashlib
import importlib.util
import lzma
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path('/var/lib/bc250/validation/video-20260922')
BASE = ROOT / 'vcn-signature-control-20260927.py'
BASE_SHA = '9cc4aa4b2a73e3403d8efe34f612a2c80d03300d48fc7ca5632fa94d7e8db236'
MODULE = ROOT / 'kernel/amdgpu-psp-type19-compare.ko'
MODULE_SHA = 'de8a7187c885200bf66bf2678dcae3d644888c343bd5cb6c10ca81a986826a36'
FIRMWARE = (
    (6, 'navi10_vcn.bin.xz',
     'a9ec155695b5020009d3986cfd4ebd00ad9ddbd12ac7e5fa15ec86b8a571dbe5',
     19, 0x6147f),
    (4, 'navi10_vcn.bin.xz',
     'a9ec155695b5020009d3986cfd4ebd00ad9ddbd12ac7e5fa15ec86b8a571dbe5',
     13, 0x6147f),
)

if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
    raise RuntimeError('pinned signature runner changed')
spec = importlib.util.spec_from_file_location('bc250_signature_control', BASE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
base.MODULE = MODULE
base.MODULE_SHA = MODULE_SHA
clock = base.clock
require = base.require


def response_lines():
    return base.response_lines()


class ComparisonExperiment(base.SignatureExperiment):
    def psp_load(self):
        require(self.power_sequence_completed, 'Power controls incomplete')
        self.require_programmed_clocks()
        path = base.auth_path()
        require(not response_lines(), 'PSP diagnostic already requested this boot')
        statuses = {}
        for index, (variant, filename, expected_sha, fw_type, offset) in enumerate(FIRMWARE):
            firmware = lzma.decompress((Path('/usr/lib/firmware/amdgpu') / filename).read_bytes())
            require(hashlib.sha256(firmware).hexdigest() == expected_sha,
                    f'Installed firmware differs from pinned {filename}')
            require(offset < len(firmware) - 256, 'Tamper outside pinned signed firmware')
            self.emit('tampered_request_intent', {
                'variant': variant, 'fw_type': fw_type, 'firmware': filename,
                'signed_byte_offset': hex(offset), 'module_sha256': MODULE_SHA})
            try:
                with path.open('wb', buffering=0) as target:
                    target.write(f'{variant}\n'.encode())
            except OSError as error:
                self.emit('tampered_syscall', {'variant': variant, 'errno': error.errno})
                require(error.errno == errno.EIO, 'Unexpected diagnostic errno')
            else:
                raise RuntimeError(f'Tampered variant {variant} unexpectedly accepted')
            lines = response_lines()
            require(len(lines) == index + 1, 'Unexpected number of PSP responses')
            line = lines[-1]
            match = re.search(r'variant=(\d+) ret=(-?\d+) status=0x([0-9a-f]+) '
                              r'fw_addr=0x([0-9a-f]+)', line)
            require(match is not None, 'Unrecognized PSP response')
            seen_variant, ret, status, address = (
                int(match[1]), int(match[2]), int(match[3], 16), int(match[4], 16))
            require(seen_variant == variant and ret == 0 and status and address == 0,
                    'Unexpected PSP transport or response fields')
            statuses[fw_type] = status
            self.emit('tampered_psp_response', {
                'variant': variant, 'fw_type': fw_type, 'status': hex(status),
                'kernel_line': line})
            require(self.smu.alive(), 'SMU lost liveness after PSP request')
        self.emit('type19_type13_comparison', {
            'type19_status': hex(statuses[19]), 'type13_status': hex(statuses[13]),
            'same_status': statuses[19] == statuses[13],
            'hardware_decode_tested': False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    require(os.geteuid() == 0, 'Root required')
    require(os.uname().release == '7.2.5-200.fc44.x86_64', 'Wrong kernel')
    cmdline = Path('/proc/cmdline').read_text().split()
    for flag in ('bc250.vcn-test=1', 'rd.driver.blacklist=amdgpu',
                 'modprobe.blacklist=amdgpu', 'systemd.unit=multi-user.target'):
        require(flag in cmdline, f'Missing one-time boot guard: {flag}')
    require(subprocess.check_output(['grub2-editenv', '-', 'list'], text=True).strip()
            == 'bc250_vcn_once=0', 'One-time boot flag not consumed')
    require(hashlib.sha256(MODULE.read_bytes()).hexdigest() == MODULE_SHA,
            'Loaded module source artifact changed')
    base.auth_path()
    clock.Experiment = ComparisonExperiment
    clock.psp_probe_path = base.auth_path
    sys.argv = [sys.argv[0], '--mode', 'psp-load-probe', '--output', args.output]
    clock.main()


if __name__ == '__main__':
    main()
