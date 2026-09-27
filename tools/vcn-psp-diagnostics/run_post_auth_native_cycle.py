#!/usr/bin/env python3
"""Run the previously tested bounded SMU client-12 cycle after a VCN PSP load.

The default action is read-only preflight. --run requires a one-time diagnostic
reboot entry and an armed recovery timer. This never touches SPI flash.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path('/var/lib/bc250/validation/video-20260922')
NATIVE = ROOT / 'vcn-native-cycle-test.py'
NATIVE_SHA = 'b1ada5a9b85c92da461a6fbacfb547caeb9a5998ff254edd042d7a2af23c7586'
MODULE = ROOT / 'kernel/amdgpu-vcn-late-psp-probe.ko'
MODULE_SHA = '77c0037854a47ee411f5cc42e5833378190360e3d69b8df7a4b9d903debaae75'
LOAD_JOURNAL = ROOT / 'kernel/late-vcn-psp-tmr-v03-20260927.jsonl'
RECOVERY = 'bc250-vcn-native-cycle-recovery.timer'
EXPECTED_ADDRESS = 0xf41fa00000
DIAGNOSTIC_ENTRY_SHA = '9675158c6e976ec9fee3741eac39d4a81e128577e62a5684049a6d5a277d6ef9'


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preconditions(run):
    require(os.geteuid() == 0, 'Root required')
    require(os.uname().release == '7.2.5-200.fc44.x86_64', 'Wrong kernel')
    flags = Path('/proc/cmdline').read_text().split()
    for flag in ('bc250.vcn-test=1', 'rd.driver.blacklist=amdgpu',
                 'modprobe.blacklist=amdgpu', 'systemd.unit=multi-user.target'):
        require(flag in flags, f'Missing diagnostic boot flag: {flag}')
    gpu = Path('/sys/bus/pci/devices/0000:01:00.0')
    require((gpu / 'vendor').read_text().strip() == '0x1002' and
            (gpu / 'device').read_text().strip() == '0x13fe' and
            (gpu / 'driver').exists(), 'Expected bound BC250 GPU')
    require(Path('/sys/module/amdgpu/parameters/bc250_vcn').read_text().strip() == 'N'
            and Path('/sys/module/amdgpu/parameters/bc250_vcn_psp_probe').read_text().strip() == 'Y',
            'Expected VCN-disabled PSP-probe module')
    require(sha(MODULE) == MODULE_SHA and sha(NATIVE) == NATIVE_SHA,
            'Diagnostic module/native helper hash mismatch')
    for service in ('sddm', 'cyan-skillfish-governor-smu', 'bc250-cu-restore'):
        require(subprocess.run(['systemctl', 'is-active', '--quiet', service]).returncode != 0,
                f'{service} is active')
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    rows = [json.loads(line) for line in LOAD_JOURNAL.read_text().splitlines()]
    require(rows and rows[0]['event'] == 'start' and rows[0]['data']['boot_id'] == boot_id,
            'VCN PSP load journal is from another boot')
    responses = [row['data'] for row in rows if row['event'] == 'psp_response']
    require(responses == [{'ret': 0, 'status': 0, 'fw_addr': EXPECTED_ADDRESS}],
            'One successful late VCN load required')
    require(any(row['event'] == 'clock_controls_restored' and row['data'] is True
                for row in rows), 'PSP trial clock controls not restored')
    if run:
        require(Path('/boot/grub2/custom.cfg').exists() and
                sha(Path('/boot/grub2/custom.cfg')) == DIAGNOSTIC_ENTRY_SHA and
                subprocess.check_output(['grub2-editenv', '-', 'list'], text=True).strip()
                == 'bc250_vcn_once=1', 'Next boot must be diagnostic')
        require(subprocess.run(['systemctl', 'is-active', '--quiet', RECOVERY]).returncode == 0,
                'Recovery timer not armed')
    else:
        require(not Path('/boot/grub2/custom.cfg').exists() and
                not subprocess.check_output(['grub2-editenv', '-', 'list'], text=True).strip(),
                'Preflight expects a cleaned temporary boot entry')
    return boot_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    boot_id = preconditions(args.run)
    spec = importlib.util.spec_from_file_location('post_auth_native_cycle', NATIVE)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    sys.path.insert(0, str(ROOT / 'bc250-smu-unlock'))
    from bc250_smu import Bc250Smu
    from bc250_smu.errors import SmuTimeout
    source = (ROOT / 'smu-sram.bin').read_bytes()
    blob = (ROOT / 'bounded-smu-reset-sender.bin').read_bytes()
    require(sha(ROOT / 'bounded-smu-reset-sender.bin') ==
            '3e35b887faf36059c64f67df5b78ec08a83f389c18abc55bed3bfaf7462ef724',
            'Bounded helper changed')

    def interrupted(signum, frame):
        raise InterruptedError(f'Signal {signum}')

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    with args.output.open('x') as evidence, open('/run/bc250-vcn-test.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def emit(event, data):
            record = {'time': time.time(), 'event': event, 'data': data}
            evidence.write(json.dumps(record) + '\n')
            evidence.flush()
            os.fsync(evidence.fileno())
            print(json.dumps(record), flush=True)

        emit('start', {'run': args.run, 'boot_id': boot_id, 'native_sha256': NATIVE_SHA,
                       'module_sha256': MODULE_SHA, 'script_sha256': sha(Path(__file__))})
        smu = Bc250Smu(timeout=1)
        probe = None
        healthy = False
        try:
            probe = native.NativeCycle(smu, SmuTimeout, source, blob, emit)
            probe.preflight()
            if args.run:
                probe.run()
            emit('completed', {'hardware_decode_verified': False,
                               'reboot_required': args.run})
        except BaseException as error:
            emit('error', repr(error))
            raise
        finally:
            try:
                if probe is not None:
                    probe.restore()
                    if probe.restored and not (probe.io_inflight or probe.transition_pending
                                               or probe.pending):
                        healthy = smu.alive()
            finally:
                smu.close()
                emit('cleanup', {'smu_alive': healthy,
                                 'ram_restored': probe.restored if probe else False,
                                 'clocks_restored': probe.clocks_restored if probe else False,
                                 'io_inflight': probe.io_inflight if probe else False,
                                 'transition_pending': probe.transition_pending if probe else False,
                                 'psp_may_be_pending': probe.pending if probe else False,
                                 'cycle_complete': probe.cycle_complete if probe else False,
                                 'reboot_required': args.run})


if __name__ == '__main__':
    main()
