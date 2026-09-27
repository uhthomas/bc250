#!/usr/bin/env python3
"""Run one signed-byte-tampered VCN PSP request in an isolated BC250 boot."""
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
BASE = ROOT / 'vcn-clock-test.py'
BASE_SHA = '1bc8d228c5e61078e5317ee12e2292c29773f1fe3ba679c51065200bfd299007'
MODULE = ROOT / 'kernel/amdgpu-psp-vcn-sig-tamper.ko'
MODULE_SHA = '90137afa3cbceba3057c1fbcd0a6afdd3a2d3b777f00633afa7c43c655db3b83'
FIRMWARE_SHA = 'a9ec155695b5020009d3986cfd4ebd00ad9ddbd12ac7e5fa15ec86b8a571dbe5'

if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
    raise RuntimeError('pinned BC250 clock/power runner changed')
spec = importlib.util.spec_from_file_location('bc250_clock_control', BASE)
clock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clock)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def auth_path():
    parameters = Path('/sys/module/amdgpu/parameters')
    require((parameters / 'bc250_vcn').read_text().strip() == 'N', 'VCN startup must be disabled')
    require((parameters / 'bc250_vcn_psp_probe').read_text().strip() == 'Y', 'Probe must be enabled')
    path = clock.find_regs().parent / 'bc250_vcn_psp_auth'
    require(path.is_file() and path.stat().st_mode & 0o777 == 0o200, 'Wrong diagnostic file')
    return path


def response_lines():
    text = subprocess.check_output(['dmesg', '--color=never'], text=True)
    return [line for line in text.splitlines() if 'BC250 VCN PSP auth:' in line and ' ret=' in line]


class SignatureExperiment(clock.Experiment):
    def probe_registers(self):
        # This control tests authentication only; do not touch VCN MMIO.
        self.require_programmed_clocks()

    def psp_load(self):
        require(self.power_sequence_completed, 'Power controls incomplete')
        self.require_programmed_clocks()
        path = auth_path()
        require(not response_lines(), 'PSP authentication already requested this boot')
        firmware = lzma.decompress(Path('/usr/lib/firmware/amdgpu/navi10_vcn.bin.xz').read_bytes())
        require(hashlib.sha256(firmware).hexdigest() == FIRMWARE_SHA,
                'Installed VCN firmware differs from pinned candidate')
        self.emit('tampered_vcn_request_intent', {'variant': 4, 'path': str(path),
                  'signed_byte_offset': '0x6147f', 'module_sha256': MODULE_SHA})
        try:
            with path.open('wb', buffering=0) as target:
                target.write(b'4\n')
        except OSError as error:
            self.emit('tampered_vcn_syscall', {'errno': error.errno})
            require(error.errno == errno.EIO, 'Unexpected probe errno')
        else:
            raise RuntimeError('Tampered firmware unexpectedly accepted')
        lines = response_lines()
        require(len(lines) == 1, 'Expected exactly one PSP response')
        line = lines[0]
        match = re.search(r'variant=(\d+) ret=(-?\d+) status=0x([0-9a-f]+) '
                          r'fw_addr=0x([0-9a-f]+)', line)
        require(match is not None, 'Unrecognized PSP response')
        variant, ret, status, address = (int(match[1]), int(match[2]),
                                         int(match[3], 16), int(match[4], 16))
        require(variant == 4 and ret == 0 and status and address == 0,
                'Unexpected PSP transport or response fields')
        self.emit('tampered_vcn_psp_response', {'status': hex(status),
                  'same_as_prior_unmodified_request': status == 0x80000029,
                  'kernel_line': line})
        require(self.smu.alive(), 'SMU lost liveness after PSP request')

    def restore(self):
        try:
            super().restore()
        except RuntimeError as error:
            if str(error) != 'Full clock state did not return to baseline':
                raise
            restored, expected = self.snapshot(), self.before
            for actual, original in zip(restored['slots'], expected['slots']):
                status = original['registers']['0x24']
                require(actual['registers']['0x24'] in (status, status & ~2),
                        'Unexpected clock status change on restore')
                actual['registers']['0x24'] = status
            require(restored == expected, 'Other SMU state changed on restore')
            self.emit('restore_known_status_settling', {'reboot_required': True})


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
    auth_path()
    clock.Experiment = SignatureExperiment
    clock.psp_probe_path = auth_path
    sys.argv = [sys.argv[0], '--mode', 'psp-load-probe', '--output', args.output]
    clock.main()


if __name__ == '__main__':
    main()
