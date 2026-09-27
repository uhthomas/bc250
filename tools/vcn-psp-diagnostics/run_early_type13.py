#!/usr/bin/env python3
"""Run one early VCN PSP load in a guarded diagnostic boot."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import lzma
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path('/var/lib/bc250/validation/video-20260922')
MODULE = ROOT / 'kernel/amdgpu-psp-early-type13.ko'
MODULE_SHA = '03f0b0c28bfeb5d20c0cb4ef7dc0b3825f78243dd4149be5477e67aae428d29c'
INTACT_MODULE = ROOT / 'kernel/amdgpu-psp-early-intact.ko'
INTACT_MODULE_SHA = '0fbf89d71c804441524889efac9351c3f8954e63d2a1d79f46f4a947322bc283'
FIRMWARE_SHA = 'a9ec155695b5020009d3986cfd4ebd00ad9ddbd12ac7e5fa15ec86b8a571dbe5'
CLOCK_SHA = '1bc8d228c5e61078e5317ee12e2292c29773f1fe3ba679c51065200bfd299007'
PRESET_SHA = 'b88384a7c092413817ba90f7d3776dfb306f62a36576c5772db29871f8c6d685'
DEPS = ('drm_display_helper', 'gpu-sched', 'amdxcp', 'ttm', 'cec',
        'drm_suballoc_helper', 'drm_exec', 'video', 'drm_ttm_helper',
        'drm_buddy', 'i2c-algo-bit', 'drm_panel_backlight_quirks')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def response_lines():
    log = subprocess.check_output(['dmesg', '--color=never'], text=True)
    return [line for line in log.splitlines() if 'BC250 PSP early:' in line]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--vram-buffer', action='store_true',
                        help='Use the kernel debug_mask=8 firmware staging option')
    parser.add_argument('--intact', action='store_true',
                        help='Submit the pinned VCN firmware without tampering')
    args = parser.parse_args()
    module = INTACT_MODULE if args.intact else MODULE
    module_sha = INTACT_MODULE_SHA if args.intact else MODULE_SHA
    require(os.geteuid() == 0, 'Root required')
    require(os.uname().release == '7.2.5-200.fc44.x86_64', 'Wrong kernel')
    cmdline = Path('/proc/cmdline').read_text().split()
    for flag in ('bc250.vcn-test=1', 'rd.driver.blacklist=amdgpu',
                 'modprobe.blacklist=amdgpu', 'systemd.unit=multi-user.target'):
        require(flag in cmdline, f'Missing diagnostic boot flag: {flag}')
    require(not subprocess.check_output(['grub2-editenv', '-', 'list'], text=True).strip()
            and not Path('/boot/grub2/custom.cfg').exists(),
            'Temporary diagnostic boot entry was not cleaned')
    require(not Path('/sys/module/amdgpu').exists(), 'GPU driver is already loaded')
    gpu = Path('/sys/bus/pci/devices/0000:01:00.0')
    require((gpu / 'vendor').read_text().strip() == '0x1002' and
            (gpu / 'device').read_text().strip() == '0x13fe', 'Unexpected GPU')
    require(sha(module) == module_sha, 'Module hash mismatch')
    firmware = lzma.decompress(Path('/usr/lib/firmware/amdgpu/navi10_vcn.bin.xz').read_bytes())
    require(hashlib.sha256(firmware).hexdigest() == FIRMWARE_SHA,
            'Installed VCN firmware differs from pinned candidate')
    require(sha(ROOT / 'vcn-clock-test.py') == CLOCK_SHA and
            sha(ROOT / 'vcn-preset-clock-test.py') == PRESET_SHA,
            'Clock helper hash mismatch')
    require(not response_lines(), 'Early PSP request already attempted this boot')
    for service in ('sddm', 'cyan-skillfish-governor-smu', 'bc250-cu-restore'):
        require(subprocess.run(['systemctl', 'is-active', '--quiet', service]).returncode != 0,
                f'{service} is active')

    spec = importlib.util.spec_from_file_location('early_type13_clock',
                                                  ROOT / 'vcn-preset-clock-test.py')
    clock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(clock)
    sys.path.insert(0, str(ROOT / 'bc250-smu-unlock'))
    from bc250_smu import Bc250Smu

    with args.output.open('x') as journal, open('/run/bc250-vcn-test.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def emit(event, data):
            record = {'time': time.time(), 'event': event, 'data': data}
            journal.write(json.dumps(record) + '\n')
            journal.flush()
            os.fsync(journal.fileno())
            print(json.dumps(record), flush=True)

        emit('start', {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                       'module_sha256': module_sha, 'script_sha256': sha(Path(__file__)),
                       'firmware_intact': args.intact})
        for dependency in DEPS:
            subprocess.run(['modprobe', dependency], check=True)
        require(not Path('/sys/module/amdgpu').exists(), 'A dependency loaded amdgpu')
        smu = Bc250Smu(timeout=2)
        pending = False
        try:
            experiment = clock.PresetClockExperiment(smu, emit)
            plan = experiment.preflight()
            try:
                experiment.pulse(plan, probe=False, power=True)
                experiment.require_programmed_clocks()
                debug_mask = 8 if args.vram_buffer else 0
                emit('insmod_intent', {'module': str(module), 'fw_type': 13,
                                       'tamper_offset': None if args.intact else '0x6147f',
                                       'debug_mask': debug_mask})
                try:
                    result = subprocess.run(['insmod', str(module), 'bc250_vcn=0',
                                             'bc250_vcn_psp_early=1',
                                             f'debug_mask={debug_mask}'], timeout=90)
                    emit('insmod_return', {'returncode': result.returncode})
                except subprocess.TimeoutExpired:
                    pending = True
                    emit('insmod_timeout', {'pending_psp_command_possible': True})
                    raise
                rows = response_lines()
                emit('kernel_rows', rows)
                kernel_log = subprocess.check_output(['dmesg', '--color=never'], text=True)
                memory_rows = [row for row in kernel_log.splitlines()
                               if ('[mmhub] page fault' in row or
                                   'in page starting at address' in row or
                                   'debug: place fw in vram' in row)]
                emit('memory_rows', memory_rows)
                responses = [row for row in rows if 'BC250 PSP early: ret=' in row]
                if len(responses) == 1:
                    match = re.search(r'ret=(-?\d+) status=0x([0-9a-f]+) '
                                      r'fw_addr=0x([0-9a-f]+)', responses[0])
                    require(match is not None, 'Malformed PSP response')
                    ret, status, address = int(match[1]), int(match[2], 16), int(match[3], 16)
                    emit('psp_response', {'ret': ret, 'status': hex(status),
                                          'fw_addr': hex(address)})
                    if ret or (not args.intact and (not status or address)):
                        pending = ret != 0
                        raise RuntimeError('Unexpected PSP response; no more requests this boot')
                else:
                    pending = True
                    raise RuntimeError('No unique PSP response; no more requests this boot')
                require(Path('/sys/module/amdgpu/parameters/debug_mask').read_text().strip()
                        == str(debug_mask), 'Requested firmware buffer mode not active')
                require(not (gpu / 'driver').exists(), 'GPU unexpectedly bound')
                emit('diagnostic_complete', {'driver_bound': False,
                                             'hardware_decode_verified': False})
            finally:
                if experiment.attempted and not pending:
                    require(smu.alive(), 'SMU not responding; leave controls for recovery boot')
                    experiment.restore()
                    emit('clock_controls_restored', True)
                elif pending:
                    emit('clock_restore_skipped', 'PSP command may still be pending; reboot required')
        finally:
            smu.close()


if __name__ == '__main__':
    main()
