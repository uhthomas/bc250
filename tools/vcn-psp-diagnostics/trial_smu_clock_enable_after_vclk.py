#!/usr/bin/env python3
"""Test the Van Gogh VCN clock-enable candidate with native VCLK active.

This is a bounded BC250 SRAM-only experiment. It uses the already tested
periodic VCLK callback and the already tested write-only SMU helper, samples
the candidate through the independent root PCI SMN window, restores the
candidate to zero and restores the helper SRAM. Cold-cycle outlet 8 afterward
to clear the one-shot clock-table generation. No BIOS/Pico flash is written.
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
import time

from bc250_smu import Bc250Smu
from bc250_smu.errors import SmuTimeout
import read_vcn_clock_enable as regs
import trial_smu_clock_callback_once as callback
import trial_smu_clock_walker as clock


HERE = Path(__file__).resolve().parent
BODY_SHA = 'eafebd45e986ab1cc1f48cfe33054942cf794ab6e27caa2d7b00f06b9957283c'
TARGET = 0x0116f200
GOVERNOR = 'cyan-skillfish-governor-smu'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load_probe():
    path = HERE / 'smu-direct-clock-read.py'
    spec = importlib.util.spec_from_file_location('smu_direct_clock_read', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Probe


def root_snapshot(expected_boot_id):
    require(regs.BOOT_ID.read_text().strip() == expected_boot_id,
            'BC250 boot changed before root SMN read')
    fd = os.open(regs.ROOT_CONFIG, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        first = {label: regs.read_smn(fd, address)
                 for label, address in regs.ADDRESSES.items()}
        second = {label: regs.read_smn(fd, address)
                  for label, address in regs.ADDRESSES.items()}
        require(first == second, 'root SMN reads changed between sweeps')
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    require(regs.BOOT_ID.read_text().strip() == expected_boot_id,
            'BC250 boot changed during root SMN read')
    return {key: f'{value:#010x}' for key, value in first.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-boot-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--pi-pdu-timer-active', action='store_true')
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    require(os.geteuid() == 0, 'root required')
    require(os.uname().release == '7.2.5-200.fc44.x86_64', 'wrong kernel')
    require(regs.BOOT_ID.read_text().strip() == args.expected_boot_id,
            'wrong BC250 boot')
    regs.identity(regs.ROOT_CONFIG, regs.ROOT_ID)
    regs.identity(regs.GPU_CONFIG, regs.GPU_ID)
    require(hashlib.sha256(clock.SOURCE.read_bytes()).hexdigest() == clock.SOURCE_SHA,
            'wrong SMU SRAM source')
    body = (HERE / 'smu-direct-clock-write.bin').read_bytes()
    require(len(body) == 90 and hashlib.sha256(body).hexdigest() == BODY_SHA,
            'wrong write-only helper')
    require(subprocess.run(['systemctl', 'is-active', '--quiet', GOVERNOR])
            .returncode == 0, 'GPU governor is not active')
    if not args.preflight_only:
        require(args.pi_pdu_timer_active, 'verified Pi PDU fallback required')

    def interrupted(signum, frame):
        raise InterruptedError(f'signal {signum}')
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)

    with args.output.open('x') as log, open('/run/bc250-vcn-test.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def emit(event, data):
            row = {'time': time.time(), 'event': event, 'data': data}
            log.write(json.dumps(row) + '\n')
            log.flush()
            os.fsync(log.fileno())
            print(event, json.dumps(data), flush=True)

        emit('start', {'boot_id': args.expected_boot_id,
                       'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       'source_sha256': clock.SOURCE_SHA,
                       'helper_sha256': BODY_SHA,
                       'preflight_only': args.preflight_only,
                       'cold_cycle_required': not args.preflight_only})
        before = root_snapshot(args.expected_boot_id)
        emit('root_before', before)
        require(before['gfx_clock_control'] == '0x48140880' and
                before['vcn_clock_code'] == '0x00000000' and
                before['vcn_clock_enable_candidate'] == '0x00000000',
                'root SMN baseline differs')

        smu = probe = None
        helper_restored = False
        target_zero_restored = False
        if args.preflight_only:
            smu = Bc250Smu(timeout=2)
            try:
                trial = clock.Trial(smu, clock.SOURCE.read_bytes(), emit)
                trial.preflight()
                Probe = load_probe()
                probe = Probe(smu, SmuTimeout, clock.SOURCE.read_bytes(),
                              body, TARGET, emit,
                              expected_body_sha=BODY_SHA,
                              expected_body_size=90, target_writes=True)
                probe.preflight()
                emit('preflight_complete', {'target_writes': False})
            finally:
                smu.close()
            return

        subprocess.run(['systemctl', 'stop', GOVERNOR], check=True, timeout=15)
        try:
            smu = Bc250Smu(timeout=2)
            source = clock.SOURCE.read_bytes()
            trial = clock.Trial(smu, source, emit)
            trial.preflight()
            callback.callback_once(trial, emit)
            after_vclk = root_snapshot(args.expected_boot_id)
            emit('root_after_vclk', after_vclk)
            require(after_vclk['vcn_clock_code'] == '0x00000010' and
                    after_vclk['vcn_clock_enable_candidate'] == '0x00000000',
                    'native VCLK or candidate pre-store state changed')

            Probe = load_probe()
            probe = Probe(smu, SmuTimeout, source, body, TARGET, emit,
                          expected_body_sha=BODY_SHA,
                          expected_body_size=90, target_writes=True)
            probe.preflight()
            probe.install()
            after_one = None
            try:
                emit('store_one_intent', {'target': hex(TARGET)})
                require(probe.invoke(0x43) == (1, 1), 'SMU store-one rejected')
                after_one = root_snapshot(args.expected_boot_id)
                emit('root_after_store_one', after_one)
                require(after_one['gfx_clock_control'] == before['gfx_clock_control'],
                        'GFX clock control changed unexpectedly')
            finally:
                if not probe.pending:
                    emit('restore_zero_intent', {'target': hex(TARGET)})
                    require(probe.invoke(0x42) == (1, 0), 'SMU store-zero rejected')
                    after_restore = root_snapshot(args.expected_boot_id)
                    emit('root_after_restore', after_restore)
                    if after_one is not None and after_one['vcn_clock_enable_candidate'] != '0x00000000':
                        require(after_restore['vcn_clock_enable_candidate'] == '0x00000000',
                                'candidate stayed set after zero restoration')
                    target_zero_restored = True
            emit('completed', {'target_zero_restored': target_zero_restored,
                               'cold_cycle_required': True})
        except BaseException as error:
            emit('error', {'detail': repr(error),
                           'cold_cycle_required': True})
            raise
        finally:
            try:
                if probe is not None and not probe.pending:
                    probe.restore()
                    helper_restored = probe.restored
            finally:
                if smu is not None:
                    smu.close()
                emit('cleanup', {'target_zero_restored': target_zero_restored,
                                 'helper_restored': helper_restored,
                                 'governor_restart_attempted': False,
                                 'cold_cycle_required': True})


if __name__ == '__main__':
    main()
