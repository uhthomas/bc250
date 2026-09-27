#!/usr/bin/env python3
"""Try one opt-in VCN 2.0.3 PSP driver bind on a guarded diagnostic boot."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import lzma
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/var/lib/bc250/validation/video-20260922')
MODULE = ROOT / 'kernel/amdgpu-vcn-psp.ko'
MODULE_SHA = '26e32fe21a83f9914cc2481a3e38be4deb56dae3c14ecf61be3d71bb5453832b'
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--vcn-disabled', action='store_true',
                        help='Control boot: same module and clock sequence without VCN registration')
    args = parser.parse_args()
    vcn_enabled = not args.vcn_disabled
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
    require(sha(MODULE) == MODULE_SHA, 'Module hash mismatch')
    firmware = lzma.decompress(Path('/usr/lib/firmware/amdgpu/navi10_vcn.bin.xz').read_bytes())
    require(hashlib.sha256(firmware).hexdigest() == FIRMWARE_SHA,
            'Installed VCN firmware differs from pinned candidate')
    require(sha(ROOT / 'vcn-clock-test.py') == CLOCK_SHA and
            sha(ROOT / 'vcn-preset-clock-test.py') == PRESET_SHA,
            'Clock helper hash mismatch')
    for service in ('sddm', 'cyan-skillfish-governor-smu', 'bc250-cu-restore'):
        require(subprocess.run(['systemctl', 'is-active', '--quiet', service]).returncode != 0,
                f'{service} is active')

    spec = importlib.util.spec_from_file_location('vcn_psp_driver_clock',
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
                       'module_sha256': MODULE_SHA, 'script_sha256': sha(Path(__file__)),
                       'firmware_sha256': FIRMWARE_SHA, 'load_type': 'PSP',
                       'vcn_enabled': vcn_enabled})
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
                emit('insmod_intent', {'module': str(MODULE), 'bc250_vcn': vcn_enabled,
                                       'load_type': 'PSP'})
                try:
                    result = subprocess.run(['insmod', str(MODULE),
                                             f'bc250_vcn={int(vcn_enabled)}'],
                                            timeout=90)
                    emit('insmod_return', {'returncode': result.returncode})
                except subprocess.TimeoutExpired:
                    pending = True
                    emit('insmod_timeout', {'pending_gpu_initialization_possible': True})
                    raise
                log = subprocess.check_output(['dmesg', '--color=never'], text=True)
                rows = [line for line in log.splitlines()
                        if ('amdgpu' in line or 'VCN' in line or 'UVD' in line or
                            '[mmhub] page fault' in line or 'in page starting at address' in line)]
                emit('kernel_rows', rows[-180:])
                bound = (gpu / 'driver').exists()
                emit('bind_result', {'driver_bound': bound,
                                     'render_nodes': [str(p) for p in
                                                      Path('/dev/dri').glob('renderD*')],
                                     'hardware_decode_verified': False})
                if bound and vcn_enabled:
                    experiment.probe_registers()
            finally:
                if experiment.attempted and not pending:
                    require(smu.alive(), 'SMU not responding; leave controls for recovery boot')
                    experiment.restore()
                    emit('clock_controls_restored', True)
                elif pending:
                    emit('clock_restore_skipped', 'GPU initialization may be pending; reboot required')
        finally:
            smu.close()


if __name__ == '__main__':
    main()
