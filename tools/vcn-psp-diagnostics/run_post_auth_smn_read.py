#!/usr/bin/env python3
"""Read one VCN reset-page SMN word after a verified intact PSP load.

The full-address read previously returned all ones with VCN clocks enabled
before authentication; the clocks-disabled variant hung. A staged diagnostic
reboot and armed recovery timer are mandatory here.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/var/lib/bc250/validation/video-20260922')
LOAD_JOURNAL = ROOT / 'kernel/late-vcn-psp-tmr-v04-20260927.jsonl'
MODULE = ROOT / 'kernel/amdgpu-vcn-late-psp-probe.ko'
MODULE_SHA = '77c0037854a47ee411f5cc42e5833378190360e3d69b8df7a4b9d903debaae75'
CLOCK_SHA = 'b88384a7c092413817ba90f7d3776dfb306f62a36576c5772db29871f8c6d685'
ENTRY_SHA = '9675158c6e976ec9fee3741eac39d4a81e128577e62a5684049a6d5a277d6ef9'
RECOVERY = 'bc250-vcn-post-auth-smn-recovery.timer'
RESET_WORD = 0x0900c004


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(os.geteuid() == 0 and os.uname().release == '7.2.5-200.fc44.x86_64',
            'Wrong host or kernel')
    flags = Path('/proc/cmdline').read_text().split()
    for flag in ('bc250.vcn-test=1', 'rd.driver.blacklist=amdgpu',
                 'modprobe.blacklist=amdgpu', 'systemd.unit=multi-user.target'):
        require(flag in flags, f'Missing diagnostic boot flag: {flag}')
    gpu = Path('/sys/bus/pci/devices/0000:01:00.0')
    require((gpu / 'vendor').read_text().strip() == '0x1002' and
            (gpu / 'device').read_text().strip() == '0x13fe' and
            (gpu / 'driver').exists(), 'Unexpected GPU state')
    require(Path('/sys/module/amdgpu/parameters/bc250_vcn').read_text().strip() == 'N'
            and Path('/sys/module/amdgpu/parameters/bc250_vcn_psp_probe').read_text().strip() == 'Y',
            'Expected VCN-disabled PSP probe module')
    require(sha(MODULE) == MODULE_SHA and sha(ROOT / 'vcn-preset-clock-test.py') == CLOCK_SHA,
            'Module or clock helper hash mismatch')
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    rows = [json.loads(line) for line in LOAD_JOURNAL.read_text().splitlines()]
    require(rows and rows[0]['event'] == 'start' and rows[0]['data']['boot_id'] == boot_id,
            'PSP load journal is from another boot')
    require([row['data'] for row in rows if row['event'] == 'psp_response'] ==
            [{'ret': 0, 'status': 0, 'fw_addr': 0xf41fa00000}],
            'One intact, successful VCN PSP load required')
    require(any(row['event'] == 'clock_controls_restored' and row['data'] is True
                for row in rows), 'PSP load clocks not restored')
    require(Path('/boot/grub2/custom.cfg').exists() and
            sha(Path('/boot/grub2/custom.cfg')) == ENTRY_SHA and
            subprocess.check_output(['grub2-editenv', '-', 'list'], text=True).strip()
            == 'bc250_vcn_once=1', 'Diagnostic recovery entry missing')
    require(subprocess.run(['systemctl', 'is-active', '--quiet', RECOVERY]).returncode == 0,
            'Recovery timer missing')
    for service in ('sddm', 'cyan-skillfish-governor-smu', 'bc250-cu-restore'):
        require(subprocess.run(['systemctl', 'is-active', '--quiet', service]).returncode != 0,
                f'{service} is active')

    spec = importlib.util.spec_from_file_location('post_auth_smn_clock',
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

        emit('start', {'boot_id': boot_id, 'module_sha256': MODULE_SHA,
                       'load_journal_sha256': sha(LOAD_JOURNAL),
                       'script_sha256': sha(Path(__file__)), 'target': hex(RESET_WORD)})
        smu = Bc250Smu(timeout=2)
        exp = clock.PresetClockExperiment(smu, emit)
        io_inflight = False
        try:
            plan = exp.preflight()
            exp.pulse(plan, probe=False, power=True)
            exp.require_programmed_clocks()
            exp.probe_registers()
            for name, address, expected in (
                    ('domain6_control', 0x0006d0f8, 0),
                    ('domain6_status', 0x0006d190, 0x01010101),
                    ('vcn_reset_page', RESET_WORD, None)):
                emit('smn_read_intent', {'name': name, 'address': hex(address),
                                         'recovery_timer_armed': True})
                io_inflight = True
                value = smu._transport.read_smu_reg(address)
                io_inflight = False
                emit('smn_read_result', {'name': name, 'value': hex(value)})
                if expected is not None:
                    require(value == expected, f'Full-address SMN control changed: {name}')
            exp.probe_registers()
            emit('completed', {'hardware_decode_verified': False})
        finally:
            if not io_inflight and exp.attempted:
                require(smu.alive(), 'SMU not responsive; defer cleanup to recovery reboot')
                exp.restore()
                emit('clock_controls_restored', True)
            else:
                emit('cleanup_deferred', {'io_inflight': io_inflight})
            smu.close()


if __name__ == '__main__':
    main()
