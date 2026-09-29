#!/usr/bin/env python3
"""One-shot BC250 VCN clock callback trial; no SRAM undo.

The SMU scheduler calls callback index 24 at 0xc760, which points to the
clock-table walker. This runner sets VCN slot 0x17 to the guarded 800 or
1250 MHz request using Q3 message 0x1d while generations match, then advances
the requested generation. The scheduler can now only see that VCN request
when it processes the table. The earlier reverse order raced the scheduler
and stalled on rollback. This experiment does not write BIOS or Pico flash.
The Pi 5 must have a verified, active PDU user timer before this runs.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import time

from bc250_smu import Bc250Smu
import trial_smu_clock_walker as clock

GOVERNOR = clock.GOVERNOR
SOURCE = clock.SOURCE
SOURCE_SHA = clock.SOURCE_SHA
GPU = clock.GPU
BOOT_ID = clock.BOOT_ID
SUPPORTED_VCLKS = (800, 1250)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def state(trial):
    smu = trial.smu
    table = clock.read(smu, clock.BASE, clock.TABLE_SIZE)
    record = clock.read(smu, clock.SLOT_RECORD, 28)
    return {
        'generation': [clock.u32(table, 0), clock.u32(table, 4)],
        'requested_word': hex(clock.u32(table, 0x14c+15*12)),
        'applied_word': hex(clock.u32(table, 0x5c+15*12)),
        'slot_code': record[2],
        'remembered_code': record[6],
        'hardware_code': clock.smn(smu, clock.CLOCK_SMN),
        'metrics': trial.sample_metrics(),
    }


def callback_once(trial, emit, deadline_seconds=3, vclk_mhz=1250):
    require(vclk_mhz in SUPPORTED_VCLKS, 'unreviewed VCN clock request')
    smu = trial.smu
    require(clock.word(smu, 0x17090) == 0xc700 and
            clock.word(smu, 0x17098) == 0xc7a0 and
            clock.word(smu, 0xc760) == 0x2e448,
            'periodic SMU clock callback differs')
    require(clock.read(smu, 0x1b154, 0x4c) ==
            trial.source[0x1b154:0x1b1a0],
            'periodic callback dispatcher differs')
    initial = state(trial)
    require(initial['generation'] == [0, 0] and
            initial['requested_word'] == '0x0' and
            initial['applied_word'] == '0x0' and
            initial['hardware_code'] == 0,
            'VCN clock changed before staging')
    emit('callback_preflight', {'slot': 0x17,
                                'callback_index': 24,
                                'callback_entry': '0x2e448',
                                'state': initial})

    # The periodic walker runs when generations differ. Keep them equal until
    # both the other zero entries and the VCN target are staged.
    for index in clock.ZERO_INDICES:
        trial.write(clock.BASE+0x14c+(index-1)*12, clock.SENTINEL)
    argument = (16 << 16) | vclk_mhz
    trial.send(argument)
    staged = state(trial)
    expected_target = hex(int.from_bytes(struct.pack('<f', float(vclk_mhz)),
                                         'little'))
    require(staged['generation'] == [0, 0] and
            staged['requested_word'] == expected_target and
            staged['applied_word'] == '0x0' and
            staged['hardware_code'] == 0,
            'clock walker ran before the trigger')
    emit('staged_before_generation', {'vclk_mhz': vclk_mhz, 'state': staged})

    # This single write triggers the scheduler's callback; never write the
    # generation backward. Recovery is a cold cycle via the Pi PDU timer.
    emit('generation_trigger_intent', {'address': hex(clock.BASE+4),
                                       'value': 1,
                                       'cold_cycle_required': True})
    trial.write(clock.BASE+4, 1)
    end = time.monotonic() + deadline_seconds
    last = None
    while time.monotonic() < end:
        current = state(trial)
        if current != last:
            emit('callback_state', current)
            last = current
        code = current['hardware_code']
        if (current['generation'] == [1, 1] and
                current['applied_word'] == expected_target and
                1 <= code <= 32 and
                current['slot_code'] == code and
                current['remembered_code'] == code and
                code == {800: 25, 1250: 16}[vclk_mhz]):
            emit('callback_completed', {'clock_code': code,
                                        'requested_vclk_mhz': vclk_mhz,
                                        'hardware_decode_tested': False,
                                        'cold_cycle_required': True})
            return current
        time.sleep(0.03)
    raise RuntimeError('periodic callback did not apply the VCN clock')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-boot-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pi-pdu-timer-active', action='store_true')
    args = parser.parse_args()
    require(args.pi_pdu_timer_active, 'verified Pi PDU timer required')
    require(os.geteuid() == 0 and
            BOOT_ID.read_text().strip() == args.expected_boot_id,
            'root or boot-ID guard failed')
    require(os.uname().release == '7.2.5-200.fc44.x86_64', 'wrong kernel')
    require((GPU/'vendor').read_text().strip() == '0x1002' and
            (GPU/'device').read_text().strip() == '0x13fe', 'wrong GPU')
    require(subprocess.run(['systemctl', 'is-active', '--quiet', GOVERNOR])
            .returncode == 0, 'GPU governor not active')
    source = SOURCE.read_bytes()
    require(hashlib.sha256(source).hexdigest() == SOURCE_SHA,
            'wrong pinned SMU image')
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
                       'source_sha256': SOURCE_SHA,
                       'runner_sha256': hashlib.sha256(
                           Path(__file__).read_bytes()).hexdigest(),
                       'cold_cycle_required': True})
        subprocess.run(['systemctl', 'stop', GOVERNOR], check=True, timeout=15)
        smu = None
        try:
            smu = Bc250Smu(timeout=2)
            trial = clock.Trial(smu, source, emit)
            trial.preflight()
            callback_once(trial, emit)
        except BaseException as error:
            emit('error', {'detail': repr(error),
                           'cold_cycle_required': True})
            raise
        finally:
            if smu is not None:
                smu.close()
            emit('cleanup', {'governor_restart_attempted': False,
                             'sram_undo_attempted': False,
                             'cold_cycle_required': True})


if __name__ == '__main__':
    main()
