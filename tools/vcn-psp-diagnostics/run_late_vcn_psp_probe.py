#!/usr/bin/env python3
"""Compare VCN registers before/after one intact PSP load on a bound GPU."""
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
MODULE = ROOT / 'kernel/amdgpu-psp-probe.ko'
MODULE_SHA = 'adbf3049907c05f795458284a6291146bc08cc486e58e9a6fded743db6bbffa5'
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


def main():
    require(os.geteuid() == 0, 'Root required')
    require(os.uname().release == '7.2.5-200.fc44.x86_64', 'Wrong kernel')
    flags = Path('/proc/cmdline').read_text().split()
    for flag in ('bc250.vcn-test=1', 'rd.driver.blacklist=amdgpu',
                 'modprobe.blacklist=amdgpu', 'systemd.unit=multi-user.target'):
        require(flag in flags, f'Missing diagnostic boot flag: {flag}')
    require(not subprocess.check_output(['grub2-editenv', '-', 'list'], text=True).strip()
            and not Path('/boot/grub2/custom.cfg').exists(),
            'Temporary diagnostic boot entry was not cleaned')
    require(not Path('/sys/module/amdgpu').exists(), 'GPU driver already loaded')
    gpu = Path('/sys/bus/pci/devices/0000:01:00.0')
    require((gpu / 'vendor').read_text().strip() == '0x1002' and
            (gpu / 'device').read_text().strip() == '0x13fe', 'Unexpected GPU')
    require(sha(MODULE) == MODULE_SHA, 'Module hash mismatch')
    fw = lzma.decompress(Path('/usr/lib/firmware/amdgpu/navi10_vcn.bin.xz').read_bytes())
    require(hashlib.sha256(fw).hexdigest() == FIRMWARE_SHA, 'VCN firmware mismatch')
    require(sha(ROOT / 'vcn-clock-test.py') == CLOCK_SHA and
            sha(ROOT / 'vcn-preset-clock-test.py') == PRESET_SHA,
            'Clock helper hash mismatch')
    for service in ('sddm', 'cyan-skillfish-governor-smu', 'bc250-cu-restore'):
        require(subprocess.run(['systemctl', 'is-active', '--quiet', service]).returncode != 0,
                f'{service} is active')

    spec = importlib.util.spec_from_file_location('late_vcn_clock',
                                                  ROOT / 'vcn-preset-clock-test.py')
    clock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(clock)
    sys.path.insert(0, str(ROOT / 'bc250-smu-unlock'))
    from bc250_smu import Bc250Smu

    output = ROOT / 'kernel/late-vcn-psp-tmr-20260927.jsonl'
    with output.open('x') as journal, open('/run/bc250-vcn-test.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def emit(event, data):
            record = {'time': time.time(), 'event': event, 'data': data}
            journal.write(json.dumps(record) + '\n')
            journal.flush()
            os.fsync(journal.fileno())
            if event != 'kernel_rows':
                print(json.dumps(record), flush=True)

        emit('start', {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                       'module_sha256': MODULE_SHA, 'firmware_sha256': FIRMWARE_SHA,
                       'script_sha256': sha(Path(__file__))})
        for dependency in DEPS:
            subprocess.run(['modprobe', dependency], check=True)
        require(not Path('/sys/module/amdgpu').exists(), 'Dependency loaded amdgpu')
        emit('insmod_intent', {'bc250_vcn': False, 'bc250_vcn_psp_probe': True})
        result = subprocess.run(['insmod', str(MODULE), 'bc250_vcn=0',
                                 'bc250_vcn_psp_probe=1'], timeout=90)
        emit('insmod_return', {'returncode': result.returncode})
        require(result.returncode == 0 and (gpu / 'driver').exists(),
                'Diagnostic GPU failed to bind')
        require(clock.clock.psp_probe_path().is_file(), 'PSP probe missing')
        smu = Bc250Smu(timeout=2)
        try:
            experiment = clock.PresetClockExperiment(smu, emit)
            plan = experiment.preflight()
            try:
                experiment.pulse(plan, probe=True, power=True)
                experiment.psp_load()
                rows = [line for line in subprocess.check_output(
                    ['dmesg', '--color=never'], text=True).splitlines()
                    if 'BC250 VCN PSP probe:' in line]
                emit('kernel_rows', rows)
                responses = [row for row in rows if 'ret=' in row]
                require(len(responses) == 1, 'Missing unique PSP response')
                match = re.search(r'ret=(-?\d+) status=0x([0-9a-f]+) '
                                  r'fw_addr=0x([0-9a-f]+)', responses[0])
                require(match is not None, 'Malformed PSP response')
                result = {'ret': int(match[1]), 'status': int(match[2], 16),
                          'fw_addr': int(match[3], 16)}
                emit('psp_response', result)
                require(result == {'ret': 0, 'status': 0, 'fw_addr': 0xf41fa00000},
                        'Unexpected PSP response; do not issue another request')
                emit('diagnostic_complete', {'hardware_decode_verified': False,
                                             'gpu_bound': (gpu / 'driver').exists()})
            finally:
                if experiment.attempted:
                    require(smu.alive(), 'SMU not responding; stop for recovery')
                    experiment.restore()
                    emit('clock_controls_restored', True)
        finally:
            smu.close()


if __name__ == '__main__':
    main()
