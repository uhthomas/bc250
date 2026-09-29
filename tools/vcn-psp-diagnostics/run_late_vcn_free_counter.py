#!/usr/bin/env python3
"""Sample the powered VCN free counter around a guarded VCPU clock toggle."""
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
MODULE = ROOT / 'kernel/amdgpu-vcn-free-counter.ko'
MODULE_SHA = 'e30611052a25aacab1007751008dea3f58d68d1f2a6a042a5fc88d0919e140ce'
FIRMWARE_SHA = 'a9ec155695b5020009d3986cfd4ebd00ad9ddbd12ac7e5fa15ec86b8a571dbe5'
CLOCK_SHA = '1bc8d228c5e61078e5317ee12e2292c29773f1fe3ba679c51065200bfd299007'
PRESET_SHA = 'b88384a7c092413817ba90f7d3776dfb306f62a36576c5772db29871f8c6d685'
DEPS = ('drm_display_helper', 'gpu-sched', 'amdxcp', 'ttm', 'cec',
        'drm_suballoc_helper', 'drm_exec', 'video', 'drm_ttm_helper',
        'drm_buddy', 'i2c-algo-bit', 'drm_panel_backlight_quirks')
STAGE_SHA = '0cca277fbeecbf71512ae253644af0964458f8324ca34df84934798e01a198dc'
ENTRY_SHA = '9675158c6e976ec9fee3741eac39d4a81e128577e62a5684049a6d5a277d6ef9'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'kernel/late-vcn-free-counter-v01-20260928.jsonl')
    parser.add_argument('--enable-vcn', action='store_true',
                        help='Run the kernel VCN initialization and ring test')
    args = parser.parse_args()
    require(args.enable_vcn, 'This trial requires --enable-vcn')
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
    stage = ROOT / 'kernel/stage-psp-boot.sh'
    require(sha(stage) == STAGE_SHA and
            sha(ROOT / 'kernel/psp-test-custom.cfg') == ENTRY_SHA,
            'Diagnostic recovery entry changed')
    for service in ('sddm', 'cyan-skillfish-governor-smu', 'bc250-cu-restore'):
        require(subprocess.run(['systemctl', 'is-active', '--quiet', service]).returncode != 0,
                f'{service} is active')

    spec = importlib.util.spec_from_file_location('late_vcn_clock',
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
            if event != 'kernel_rows':
                print(json.dumps(record), flush=True)

        emit('start', {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                       'module_sha256': MODULE_SHA, 'firmware_sha256': FIRMWARE_SHA,
                       'script_sha256': sha(Path(__file__))})
        for dependency in DEPS:
            subprocess.run(['modprobe', dependency], check=True)
        require(not Path('/sys/module/amdgpu').exists(), 'Dependency loaded amdgpu')
        smu = Bc250Smu(timeout=2)
        try:
            experiment = clock.PresetClockExperiment(smu, emit)
            plan = experiment.preflight()
            try:
                # The patched PSP driver needs this domain ready during SETUP_TMR.
                experiment.pulse(plan, probe=False, power=True)
                experiment.require_programmed_clocks()
                # SETUP_TMR itself runs the experimental writes, so stage a
                # diagnostic recovery entry before loading the GPU driver.
                subprocess.run(['unshare', '--mount', '--propagation', 'private',
                                'bash', str(stage)], check=True)
                require(subprocess.check_output(['grub2-editenv', '-', 'list'],
                                                text=True).strip() == 'bc250_vcn_once=1'
                        and sha(Path('/boot/grub2/custom.cfg')) == ENTRY_SHA,
                        'Diagnostic recovery entry not armed')
                emit('recovery_entry_staged', {'sha256': ENTRY_SHA})
                emit('insmod_intent', {'bc250_vcn': args.enable_vcn,
                                      'bc250_vcn_psp_probe': not args.enable_vcn})
                result = subprocess.run(['insmod', str(MODULE),
                                         f'bc250_vcn={int(args.enable_vcn)}',
                                         f'bc250_vcn_psp_probe={int(not args.enable_vcn)}'],
                                        timeout=90)
                emit('insmod_return', {'returncode': result.returncode})
                emit('kernel_rows_after_insmod', [line for line in subprocess.check_output(
                    ['dmesg', '--color=never'], text=True).splitlines()
                    if any(mark in line.lower() for mark in
                           ('amdgpu', 'vcn', 'uvd', 'psp', 'setup_tmr'))][-120:])
                trace = [line for line in subprocess.check_output(
                    ['dmesg', '--color=never'], text=True).splitlines()
                    if any(mark in line for mark in ('BC250 VCN trace', 'BC250 VCN MC',
                         'BC250 VCN LMI', 'BC250 VCN UVDW', 'BC250 VCN postpower',
                         'BC250 VCN allocation', 'BC250 VCN pinned map',
                         'BC250 VCN VCPU', 'BC250 VCN version',
                         'BC250 VCN free counter'))]
                emit('vcn_register_trace', trace)
                pre = [line for line in trace if 'BC250 VCN postpower pre:' in line]
                after = [line for line in trace if 'BC250 VCN postpower reload:' in line]
                require(len(pre) == len(after) == 1, 'Missing or duplicate postpower samples')
                pre_pgfsm = re.search(r'pgfsm=([0-9a-f]{8})', pre[0])
                reload_status = re.search(r'ret=(-?\d+) psp_status=([0-9a-f]{8}) '
                                          r'pgfsm=([0-9a-f]{8})', after[0])
                require(pre_pgfsm is not None and reload_status is not None,
                        'Malformed postpower samples')
                emit('postpower_result', {
                    'pgfsm_before': int(pre_pgfsm[1], 16),
                    'psp_return': int(reload_status[1]),
                    'psp_status': int(reload_status[2], 16),
                    'pgfsm_after': int(reload_status[3], 16),
                    'firmware_cache_readback_known_valid': False,
                    'hardware_decode_verified': False,
                })
                clock_rows = [line for line in trace if
                              'BC250 VCN VCPU clock readback:' in line or
                              'BC250 VCN VCPU clock probe skipped:' in line]
                require(len(clock_rows) == 1, 'Missing or duplicate VCPU clock sample')
                match = re.search(r'before=([0-9a-f]{8}) cleared=([0-9a-f]{8}) '
                                  r'restored=([0-9a-f]{8})', clock_rows[0])
                emit('vcpu_clock_readback', {
                    'line': clock_rows[0],
                    'guard_passed': match is not None,
                    'before': int(match[1], 16) if match else None,
                    'cleared': int(match[2], 16) if match else None,
                    'restored': int(match[3], 16) if match else None,
                })
                counter_rows = [line for line in trace if
                                'BC250 VCN free counter:' in line]
                require(len(counter_rows) == 1, 'Missing or duplicate free-counter sample')
                counter = re.search(r'before=([0-9a-f]{8}) enabled=([0-9a-f]{8}) '
                                    r'disabled=([0-9a-f]{8}) restored=([0-9a-f]{8})',
                                    counter_rows[0])
                require(counter is not None, 'Malformed free-counter sample')
                emit('vcn_free_counter', {
                    'before': int(counter[1], 16),
                    'enabled': int(counter[2], 16),
                    'disabled': int(counter[3], 16),
                    'restored': int(counter[4], 16),
                })
                if args.enable_vcn:
                    emit('vcn_init_result', {'gpu_bound': (gpu / 'driver').exists(),
                                             'insmod_returncode': result.returncode,
                                             'hardware_decode_verified': False})
                    return
                require(result.returncode == 0 and (gpu / 'driver').exists(),
                        'Diagnostic GPU failed to bind')
                require(clock.clock.psp_probe_path().is_file(), 'PSP probe missing')
                experiment.probe_registers()
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
                                             'gpu_bound': (gpu / 'driver').exists(),
                                             'recovery_entry_still_staged': True})
            finally:
                if experiment.attempted:
                    require(smu.alive(), 'SMU not responding; stop for recovery')
                    experiment.restore()
                    emit('clock_controls_restored', True)
        finally:
            smu.close()


if __name__ == '__main__':
    main()
