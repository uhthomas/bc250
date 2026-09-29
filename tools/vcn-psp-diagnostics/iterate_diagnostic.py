#!/usr/bin/env python3
"""Run guarded BC250 VCN trials without restoring Fedora between cold cycles.

This orchestrates the existing pinned diagnostic runner and Pi PDU helper. It
does not write the BC250 BIOS EEPROM or Pico QSPI flash. A retained-state trial
keeps the native SMU clock and domain settings when guarded cleanup succeeds.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys
import time
import uuid


BC = 'root@192.168.0.49'
PI = 'pi@192.168.0.27'
ROOT = '/var/lib/bc250/validation/video-20260922'
KERNEL = f'{ROOT}/kernel'
RUNNER = f'{KERNEL}/run_late_vcn_native_clock_trial.py'
SMU_READER = f'{KERNEL}/read_retained_vcn_smu.py'
ENTRY_SHA = '9675158c6e976ec9fee3741eac39d4a81e128577e62a5684049a6d5a277d6ef9'
ACTIVE_UF2 = '/home/pi/bc250-vcn-psp-bo-fetch-20260929/bc250_psp_bo_fetch.uf2'
ACTIVE_SHA = '0922b436f613cfa9af982a505b752232527fb8ba18164cfe1f6779693c3915bb'
PASS_UF2 = '/home/pi/bc250-pico2-20260926/candidates/cs-pass-v02/bc250_cs_pass.uf2'
PASS_SHA = '70b5af760d37bd4a30b4c0efc35d758cbfb5c415563a63b3f093844660e3829d'
PDU = '/home/pi/bc250-pdu/pi_pdu_watchdog.py'
PICOTOOL = '/home/pi/.local/bin/picotool'
RESULTS = Path(__file__).resolve().parents[2] / 'output/video-decode-20260922/results'
FLAGS = {'bc250.vcn-test=1', 'rd.driver.blacklist=amdgpu',
         'modprobe.blacklist=amdgpu', 'systemd.unit=multi-user.target'}

STATE_SCRIPT = '''
import hashlib, json, pathlib, subprocess
p = pathlib.Path
entry = p('/boot/grub2/custom.cfg')
print(json.dumps({
    'boot_id': p('/proc/sys/kernel/random/boot_id').read_text().strip(),
    'cmdline': p('/proc/cmdline').read_text().strip(),
    'kernel': subprocess.check_output(['uname', '-r'], text=True).strip(),
    'grubenv': subprocess.check_output(['grub2-editenv', '-', 'list'], text=True).strip(),
    'custom_sha': hashlib.sha256(entry.read_bytes()).hexdigest() if entry.exists() else None,
    'boot_options': subprocess.check_output(['findmnt', '-n', '-o', 'OPTIONS', '/boot'], text=True).strip(),
    'amdgpu_loaded': p('/sys/module/amdgpu').exists(),
}))
'''
PICO_SCRIPT = '''
import serial
with serial.Serial('/dev/ttyACM0', 115200, timeout=2) as port:
    port.reset_input_buffer()
    port.write(b'status\\n')
    port.flush()
    print(port.readline().decode(errors='replace').strip())
'''


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def ssh_argv(host, command):
    return ['ssh', '-F', '/dev/null', '-o', 'BatchMode=yes',
            '-o', 'ConnectTimeout=4', '-o', 'ConnectionAttempts=1',
            '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
            host, shlex.join(command)]


def remote(host, command, *, timeout=20, check=True):
    result = subprocess.run(ssh_argv(host, command), capture_output=True,
                            text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'{host}: {shlex.join(command)} failed '
                           f'({result.returncode}): {result.stderr[-1000:]} '
                           f'{result.stdout[-1000:]}')
    return result


def state():
    data = json.loads(remote(BC, ['python3', '-c', STATE_SCRIPT]).stdout)
    flags = set(data['cmdline'].split())
    data['kind'] = ('diagnostic' if FLAGS <= flags and not data['amdgpu_loaded']
                    else 'normal' if not FLAGS & flags and data['amdgpu_loaded']
                    else 'unknown')
    return data


def pico_status():
    return remote(PI, ['python3', '-c', PICO_SCRIPT]).stdout.strip()


def require_clean_boot(data, kind):
    require(data['kind'] == kind, f'expected {kind} boot: {data}')
    require(data['kernel'] == '7.2.5-200.fc44.x86_64', 'unexpected kernel')
    require(data['grubenv'] == '' and data['custom_sha'] is None,
            'temporary GRUB entry still present')
    require(data['boot_options'].split(',')[0] == 'ro', '/boot is not read-only')


def require_staged(data):
    require(data['grubenv'] == 'bc250_vcn_once=1' and
            data['custom_sha'] == ENTRY_SHA and
            data['boot_options'].split(',')[0] == 'ro',
            f'one-shot diagnostic entry not staged as expected: {data}')


def require_consumed(data):
    require(data['kind'] == 'diagnostic' and
            data['grubenv'] == 'bc250_vcn_once=0' and
            data['custom_sha'] == ENTRY_SHA and
            data['boot_options'].split(',')[0] == 'ro',
            f'diagnostic one-shot entry not consumed as expected: {data}')


def require_pico(status, profile):
    if profile == 'active':
        tokens = ('profile=vcn-psp-bo-fetch ', 'mode=2', 'fault=0',
                  'host_cs=1')
    elif profile == 'premap':
        tokens = ('profile=vcn-delayed-map-windows-premap-bo-fetch ',
                  'mode=2', 'fault=0', 'host_cs=1')
    elif profile == 'reset':
        tokens = ('profile=vcn-delayed-map-reset-premap-bo-fetch ',
                  'mode=2', 'fault=0', 'host_cs=1')
    elif profile == 'tmrreset':
        tokens = ('profile=vcn-delayed-map-reset-premap-tmr-fetch ',
                  'mode=2', 'fault=0', 'host_cs=1')
    elif profile == 'tmrwriter':
        tokens = ('profile=vcn-tmr-rbc-writer ',
                  'mode=2', 'fault=0', 'host_cs=1')
    elif profile == 'tmrwriterstage':
        tokens = ('profile=vcn-tmr-rbc-writer-stage ',
                  'mode=2', 'fault=0', 'host_cs=1')
    else:
        tokens = ('BC250-PICO2-CS-PASS v2 ', 'armed=1', 'gate=1',
                  'host_cs=1', 'miso=INPUT', 'bios_write=UNAVAILABLE')
    require(all(token in status for token in tokens),
            f'Pico is not in guarded {profile} mode: {status}')


def pin_uf2(path, expected):
    actual = remote(PI, ['sha256sum', path]).stdout.split()[0]
    require(actual == expected, f'Pi UF2 hash changed: {path}: {actual}')


def load_active():
    current = pico_status()
    if 'profile=vcn-psp-bo-fetch ' in current:
        require_pico(current, 'active')
        print('Pico active profile already armed; keeping it in SRAM.', flush=True)
        return
    require_pico(current, 'pass')
    pin_uf2(ACTIVE_UF2, ACTIVE_SHA)
    result = remote(PI, ['python3', '/home/pi/load_and_arm_ram.py',
                         '--uf2', ACTIVE_UF2, '--profile', 'vcn-psp-bo-fetch',
                         '--picotool', PICOTOOL], timeout=30)
    print(result.stdout.strip(), flush=True)
    require_pico(pico_status(), 'active')


def load_pass():
    current = pico_status()
    if 'BC250-PICO2-CS-PASS v2 ' in current:
        require_pico(current, 'pass')
        print('Pico CS-PASS already armed.', flush=True)
        return
    current_profile = ('tmrwriterstage' if
                       'profile=vcn-tmr-rbc-writer-stage ' in current else
                       'tmrwriter' if
                       'profile=vcn-tmr-rbc-writer ' in current else
                       'tmrreset' if
                       'profile=vcn-delayed-map-reset-premap-tmr-fetch '
                       in current else 'reset' if
                       'profile=vcn-delayed-map-reset-premap-bo-fetch '
                       in current else 'premap' if
                       'profile=vcn-delayed-map-windows-premap-bo-fetch '
                       in current else 'active')
    require_pico(current, current_profile)
    pin_uf2(PASS_UF2, PASS_SHA)
    result = remote(PI, ['python3', '/home/pi/load_and_arm_cs_pass.py',
                         '--uf2', PASS_UF2, '--picotool', PICOTOOL], timeout=30)
    print(result.stdout.strip(), flush=True)
    require_pico(pico_status(), 'pass')


def stage():
    before = state()
    require_clean_boot(before, before['kind'])
    require(before['kind'] in ('normal', 'diagnostic'), 'unknown boot kind')
    remote(BC, ['unshare', '-m', '--', 'bash', f'{KERNEL}/stage_diagnostic_boot.sh'],
           timeout=20)
    after = state()
    require(after['boot_id'] == before['boot_id'], 'boot changed during staging')
    require_staged(after)
    print(f'Diagnostic one-shot staged on {before["boot_id"]}.', flush=True)


def cleanup_consumed():
    before = state()
    require_consumed(before)
    remote(BC, ['unshare', '-m', '--', 'bash',
                f'{KERNEL}/cleanup_consumed_diagnostic_boot.sh'], timeout=20)
    after = state()
    require(after['boot_id'] == before['boot_id'], 'boot changed during cleanup')
    require_clean_boot(after, 'diagnostic')
    print(f'Diagnostic boot ready: {after["boot_id"]}.', flush=True)
    return after


def pdu_status():
    result = remote(PI, ['/usr/bin/python3', PDU, '--status'], timeout=35)
    require('Outlet 8: On' in result.stdout and
            'Outlet grouping: disabled' in result.stdout,
            f'PDU preflight failed: {result.stdout}')


def arm_timer():
    unit = 'bc250-vcn-batch-' + uuid.uuid4().hex[:12]
    remote(PI, ['systemd-run', '--user', '--on-active=10min',
                f'--unit={unit}', '/usr/bin/python3', PDU, '--reboot'],
           timeout=20)
    active = remote(PI, ['systemctl', '--user', 'is-active',
                         f'{unit}.timer']).stdout.strip()
    require(active == 'active', f'Pi recovery timer did not arm: {unit}: {active}')
    print(f'Pi recovery timer armed: {unit}.timer (10 min).', flush=True)
    return unit


def stop_timer(unit):
    remote(PI, ['systemctl', '--user', 'stop', f'{unit}.timer'])
    active = remote(PI, ['systemctl', '--user', 'is-active',
                         f'{unit}.timer'], check=False).stdout.strip()
    require(active != 'active', f'Pi recovery timer remains active: {unit}')
    print(f'Pi recovery timer stopped: {unit}.timer.', flush=True)


def pdu_reboot():
    print('Cold-cycling BC250 outlet 8.', flush=True)
    result = remote(PI, ['/usr/bin/python3', PDU, '--reboot'], timeout=35)
    require('Outlet 8 reboot accepted' in result.stdout,
            f'PDU did not acknowledge reboot: {result.stdout}')


def wait_new_boot(old_id, *, timeout=300):
    deadline = time.monotonic() + timeout
    next_report = time.monotonic()
    while time.monotonic() < deadline:
        try:
            current = state()
            if current['boot_id'] != old_id and current['kind'] != 'unknown':
                print(f'BC250 rebooted: {current["boot_id"]} '
                      f'({current["kind"]}).', flush=True)
                return current
        except (OSError, subprocess.TimeoutExpired, ValueError, RuntimeError):
            pass
        if time.monotonic() >= next_report:
            print('Waiting for BC250 SSH after cold cycle...', flush=True)
            next_report = time.monotonic() + 20
        time.sleep(3)
    raise RuntimeError('BC250 did not return after cold cycle; '
                       'Pi recovery timer remains armed')


def cycle(old_id, expected, timer):
    pdu_reboot()
    new = wait_new_boot(old_id)
    if new['kind'] == 'diagnostic':
        require_consumed(new)
        # The board has booted; a second PDU cycle would only disturb cleanup.
        stop_timer(timer)
        cleanup_consumed()
    else:
        require_clean_boot(new, 'normal')
        stop_timer(timer)
    require(new['kind'] == expected,
            f'expected {expected} after cold cycle, got {new["kind"]}')
    return new


def capture_remote(command, destination):
    try:
        result = remote(BC, command, timeout=25)
        destination.write_text(result.stdout)
        return {'path': str(destination),
                'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
                'bytes': destination.stat().st_size}
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as error:
        return {'error': str(error)}


def enter():
    current = state()
    require_clean_boot(current, 'normal')
    pdu_status()
    load_active()
    stage()
    timer = arm_timer()
    cycle(current['boot_id'], 'diagnostic', timer)
    require_pico(pico_status(), 'active')


def retained_smu(boot_id, vclk_mhz):
    result = remote(BC, ['env', f'PYTHONPATH={ROOT}/bc250-smu-unlock',
                         'python3', SMU_READER, '--expected-boot-id', boot_id],
                    timeout=25)
    data = json.loads(result.stdout)
    expected_word = f'{struct.unpack("<I", struct.pack("<f", float(vclk_mhz)))[0]:#010x}'
    require(data['generation'] == [1, 1] and
            data['requested_word'] == expected_word and
            data['applied_word'] == expected_word and
            data['vclk_mhz_from_applied_word'] == float(vclk_mhz) and
            1 <= data['slot_code'] <= 32 and
            data['slot_code'] == data['hardware_code'] ==
            data['remembered_code'] and
            data['hardware_code'] == {800: 25, 1250: 16}[vclk_mhz] and
            data['slot_enables'] == [1, 1, 1] and
            data['domain_control'] == 0,
            f'native VCN SMU setup did not remain active: {data}')
    return data


def trial(kind, *, retain=False, vclk_mhz=1250, cycle_domain6_once=False):
    require(re.fullmatch(r'[a-z0-9-]+', kind), 'invalid module kind')
    require(vclk_mhz in (800, 1250), 'unreviewed VCN clock request')
    current = state()
    require_clean_boot(current, 'diagnostic')
    profile = ('tmrwriterstage' if kind in ('rbc-tmr-psp-writer-stage',
                                           'vcpu-marker-stub',
                                           'vcpu-early-store',
                                           'vcpu-harvest-try') else
               'tmrwriter' if kind in ('rbc-tmr-psp-writer',
                                     'vcpu-spin-stub',
                                     'vcpu-spin-ring-reset') else
               'tmrreset' if kind in ('rbc-tmr-reset-oracle',
                                    'vcpu-early-ring-reset',
                                    'rbc-tmr-bar-oracle',
                                    'rbc-tmr-perfmon-phase',
                                    'vcpu-clock-differential',
                                    'vcpu-memory-witness',
                                    'mmsch-ungate',
                                    'rbc-clock-status-calibration',
                                    'fetch-bar-differential',
                                    'dpg-clock-report',
                                    'vcpu-address-fault',
                                    'vcpu-pif-interrupt',
                                    'vcpu-report-force',
                                    'vcpu-report-handoff') else
               'reset' if kind == 'rbc-reset-oracle' else
               'premap' if kind in ('rbc-cache-readback',
                                    'rbc-perfmon-control',
                                    'rbc-perfmon-phase') else 'active')
    require_pico(pico_status(), profile)
    pdu_status()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    cycle_suffix = '-dom6-cycle' if cycle_domain6_once else ''
    name = (f'bc250-vcn-{kind}-vclk{vclk_mhz}{cycle_suffix}-'
            f'{stamp}-{uuid.uuid4().hex[:6]}')
    remote_journal = f'{KERNEL}/{name}.jsonl'
    argv = ['env', f'PYTHONPATH={ROOT}/bc250-smu-unlock', 'python3', RUNNER,
            '--expected-boot-id', current['boot_id'], '--module-kind', kind,
            '--vclk-mhz', str(vclk_mhz), '--output', remote_journal]
    if cycle_domain6_once:
        argv.append('--cycle-domain6-once')
    preflight = remote(BC, argv + ['--preflight-only'], timeout=45)
    require('"preflight_only": true' in preflight.stdout,
            'native-clock module preflight did not complete')
    print(f'Preflight passed for {kind} on {current["boot_id"]}.', flush=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    timer = arm_timer()
    print(f'Running {kind}; results: {name}.', flush=True)
    try:
        result = remote(BC, argv + ['--pi-pdu-timer-active'],
                        timeout=190, check=False)
        trial_result = {'returncode': result.returncode,
                        'stdout_tail': result.stdout[-6000:],
                        'stderr_tail': result.stderr[-2000:]}
    except subprocess.TimeoutExpired as error:
        trial_result = {'timeout': str(error)}
    summary = (f'returncode={trial_result["returncode"]}'
               if 'returncode' in trial_result else 'SSH timed out')
    print(f'Trial outcome: {summary}; full output is in the evidence.', flush=True)
    evidence = {
        'journal': capture_remote(['cat', remote_journal], RESULTS / f'{name}.jsonl'),
        'dmesg': capture_remote(['dmesg', '--color=never'], RESULTS / f'{name}.dmesg'),
        'pico_status': pico_status(),
    }
    if retain and trial_result.get('returncode') == 0:
        try:
            after = state()
            require(after['boot_id'] == current['boot_id'],
                    'board rebooted during retained trial')
            require_staged(after)
            require(after['amdgpu_loaded'], 'test driver disappeared unexpectedly')
            smu_before_unload = retained_smu(current['boot_id'], vclk_mhz)
            require(not smu_before_unload['gpu_driver_bound'],
                    'test driver is bound to the GPU')
            remote(BC, ['rmmod', 'amdgpu'], timeout=45)
            unloaded = state()
            require(unloaded['boot_id'] == current['boot_id'] and
                    unloaded['kind'] == 'diagnostic' and
                    not unloaded['amdgpu_loaded'],
                    'test driver did not unload cleanly')
            smu_after_unload = retained_smu(current['boot_id'], vclk_mhz)
            require(not smu_after_unload['amdgpu_module_loaded'] and
                    not smu_after_unload['gpu_driver_bound'],
                    'test driver remained active after unload')
            remote(BC, ['unshare', '-m', '--', 'bash',
                        f'{KERNEL}/cleanup_unconsumed_diagnostic_boot.sh'],
                   timeout=25)
            require_clean_boot(state(), 'diagnostic')
            stop_timer(timer)
            report = {'module_kind': kind, 'requested_vclk_mhz': vclk_mhz,
                      'cycle_domain6_once': cycle_domain6_once,
                      'boot_id': current['boot_id'],
                      'trial': trial_result, 'evidence': evidence,
                      'smu_before_unload': smu_before_unload,
                      'smu_after_unload': smu_after_unload,
                      'same_boot_retained': True}
            report_path = RESULTS / f'{name}.json'
            report_path.write_text(json.dumps(report, indent=2) + '\n')
            print(f'SMU clock and domain setup retained on {current["boot_id"]}. '
                  f'Saved {report_path}', flush=True)
            return
        except (OSError, subprocess.TimeoutExpired, ValueError, RuntimeError) as error:
            print(f'Retained-state checks failed: {error}; '
                  'recovering by cold cycle.', flush=True)
    # An early runner or retained-state failure can precede recovery-entry
    # staging. Keep the Pi PDU timer armed until recovery is verified.
    before_cycle = state()
    require(before_cycle['boot_id'] == current['boot_id'],
            'board rebooted during trial; inspect recovery before proceeding')
    if before_cycle['grubenv'] == '' and before_cycle['custom_sha'] is None:
        stage()
    else:
        require_staged(before_cycle)
    new = cycle(current['boot_id'], 'diagnostic', timer)
    require_pico(pico_status(), profile)
    report = {'module_kind': kind, 'requested_vclk_mhz': vclk_mhz,
              'cycle_domain6_once': cycle_domain6_once,
              'prior_boot_id': current['boot_id'],
              'new_boot_id': new['boot_id'], 'trial': trial_result,
              'evidence': evidence}
    report_path = RESULTS / f'{name}.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Saved {report_path}', flush=True)
    require(trial_result.get('returncode') == 0,
            'trial failed or timed out; diagnostic boot recovered; inspect evidence')


def finish():
    current = state()
    require_clean_boot(current, 'diagnostic')
    pdu_status()
    load_pass()
    timer = arm_timer()
    cycle(current['boot_id'], 'normal', timer)
    require_pico(pico_status(), 'pass')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='show current BC250 and Pico states')
    commands.add_parser('enter', help='enter diagnostic boot from normal Fedora')
    run = commands.add_parser('trial', help='run one pinned module and return to diagnostics')
    run.add_argument('module_kind')
    run.add_argument('--vclk-mhz', type=int, choices=(800, 1250), default=1250)
    run.add_argument('--cycle-domain6-once', action='store_true')
    retained = commands.add_parser('trial-retain',
                                   help='keep native VCN SMU state if cleanup passes')
    retained.add_argument('module_kind')
    retained.add_argument('--vclk-mhz', type=int, choices=(800, 1250),
                          default=1250)
    retained.add_argument('--cycle-domain6-once', action='store_true')
    commands.add_parser('finish', help='restore CS-PASS and normal Fedora')
    args = parser.parse_args()
    try:
        if args.command == 'status':
            print(json.dumps({'bc250': state(), 'pico': pico_status()}, indent=2))
        elif args.command == 'enter':
            enter()
        elif args.command == 'trial':
            trial(args.module_kind, vclk_mhz=args.vclk_mhz,
                  cycle_domain6_once=args.cycle_domain6_once)
        elif args.command == 'trial-retain':
            trial(args.module_kind, retain=True, vclk_mhz=args.vclk_mhz,
                  cycle_domain6_once=args.cycle_domain6_once)
        else:
            finish()
    except (OSError, subprocess.TimeoutExpired, ValueError, RuntimeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
