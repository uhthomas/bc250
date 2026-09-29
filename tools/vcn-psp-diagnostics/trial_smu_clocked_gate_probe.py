#!/usr/bin/env python3
"""Probe BC250 VCN gates after native SMU clock application; cold cycle after.

Requires the one-shot callback trial to have completed on this exact boot and
an independently active Pi 5 PDU timer. Only the three VCN slot enables,
domain-6 gate, and previously measured idempotent domain-up commands are
written. No BIOS/Pico flash or SMU SRAM undo occurs.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import time

from bc250_smu import Bc250Smu
import trial_smu_clock_walker as clock

ROOT = Path('/sys/kernel/debug/dri')
WIN = 0x01100000
ENABLES = (0x6d108, 0x6d130, 0x6d158)
CONTROL = 0x6d0f8
POWER_COMMAND = 0x6d17c
POWER_RAIL = 0x6d184
POWER_STATUS = 0x6d190


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def find_regs():
    matches = set()
    for directory in ROOT.glob('[0-9]*'):
        if (directory/'amdgpu_regs').exists() and (directory/'name').exists():
            if '0000:01:00.0' in (directory/'name').read_text():
                matches.add((directory/'amdgpu_regs').resolve())
    require(len(matches) == 1, 'expected one amdgpu_regs device')
    return matches.pop()


def probe_regs(path, emit):
    names = (('PSP_C2PMSG_70', (0x16040+70)*4),
             ('UVD_VERSION', 0x20f24),
             ('UVD_STATUS', 0x201bc),
             ('UVD_POWER_STATUS', 0x1f810))
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    values = {}
    try:
        for name, address in names:
            emit('mmio_read_intent', {'name': name, 'address': hex(address)})
            data = os.pread(fd, 4, address)
            require(len(data) == 4, f'short read for {name}')
            values[name] = struct.unpack('<I', data)[0]
            emit('mmio_result', {'name': name, 'value': hex(values[name])})
    finally:
        os.close(fd)
    require(values['PSP_C2PMSG_70'] != 0xffffffff,
            'PSP control is unavailable; MMIO path suspect')
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-boot-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pi-pdu-timer-active', action='store_true')
    args = parser.parse_args()
    require(args.pi_pdu_timer_active, 'verified Pi PDU timer required')
    require(os.geteuid() == 0 and
            clock.BOOT_ID.read_text().strip() == args.expected_boot_id,
            'root or boot-ID guard failed')
    require(os.uname().release == '7.2.5-200.fc44.x86_64', 'wrong kernel')
    require((clock.GPU/'vendor').read_text().strip() == '0x1002' and
            (clock.GPU/'device').read_text().strip() == '0x13fe', 'wrong GPU')
    require(subprocess.run(['systemctl', 'is-active', '--quiet',
                            'cyan-skillfish-governor-smu']).returncode != 0,
            'GPU governor must remain stopped during volatile clock trial')
    with args.output.open('x') as log, open('/run/bc250-vcn-test.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def emit(event, data):
            log.write(json.dumps({'time': time.time(), 'event': event,
                                  'data': data}) + '\n')
            log.flush()
            os.fsync(log.fileno())
            print(event, json.dumps(data), flush=True)
        emit('start', {'boot_id': args.expected_boot_id,
                       'runner_sha256': hashlib.sha256(
                           Path(__file__).read_bytes()).hexdigest(),
                       'cold_cycle_required': True})
        smu = Bc250Smu(timeout=2)
        try:
            require(smu.alive(), 'SMU liveness failed')
            table = clock.read(smu, clock.BASE, clock.TABLE_SIZE)
            target_word = struct.unpack('<I', struct.pack('<f', 1250.0))[0]
            require([clock.u32(table, 0), clock.u32(table, 4)] == [1, 1] and
                    clock.u32(table, 0x14c+15*12) == target_word and
                    clock.u32(table, 0x5c+15*12) == target_word,
                    'native callback state differs')
            record = clock.read(smu, clock.SLOT_RECORD, 28)
            require(record[2] == record[6] == 16 and
                    clock.smn(smu, clock.CLOCK_SMN) == 16 and
                    clock.metrics()['vclk_mhz'] == 1250,
                    'VCN native clock was not active')
            require([clock.smn(smu, a) for a in ENABLES] == [0, 0, 0] and
                    clock.smn(smu, CONTROL) == 2,
                    'VCN gate/enables differ')
            require(clock.word(smu, 0xf714) == 0x10101 and
                    clock.smn(smu, POWER_STATUS) == 0x01010101 and
                    clock.smn(smu, POWER_COMMAND) == 0 and
                    clock.smn(smu, POWER_RAIL) == 0,
                    'domain-6 power baseline differs')
            path = find_regs()
            emit('preflight', {'vclk_mhz': 1250, 'clock_code': 16,
                               'enables': [0, 0, 0], 'domain_control': 2})
            for address in ENABLES:
                emit('smu_write_intent', {'address': hex(WIN+address), 'value': 1})
                smu.smu_write32(WIN+address, 1)
                require(clock.smn(smu, address) == 1,
                        f'enable did not read back at {address:#x}')
            emit('smu_write_intent', {'address': hex(WIN+CONTROL), 'value': 0})
            smu.smu_write32(WIN+CONTROL, 0)
            require(clock.smn(smu, CONTROL) == 0, 'domain gate did not release')
            first = probe_regs(path, emit)
            emit('after_gate', {'vclk_mhz': clock.metrics()['vclk_mhz'],
                                'vcn_all_ones': all(first[k] == 0xffffffff
                                                    for k in ('UVD_VERSION',
                                                              'UVD_STATUS',
                                                              'UVD_POWER_STATUS'))})
            for address, value, poll, mask, expected in (
                (POWER_COMMAND, 1, POWER_STATUS, 0x100, 0x100),
                (POWER_RAIL, 0x10000, POWER_RAIL, 0x10000, 0),
            ):
                emit('power_command_intent', {'address': hex(WIN+address),
                                              'value': hex(value)})
                smu.smu_write32(WIN+address, value)
                deadline = time.monotonic() + 0.5
                while clock.smn(smu, poll) & mask != expected:
                    require(time.monotonic() < deadline,
                            'domain-6 power acknowledgement timed out')
                    time.sleep(0.01)
            second = probe_regs(path, emit)
            emit('after_power', {'vclk_mhz': clock.metrics()['vclk_mhz'],
                                 'vcn_all_ones': all(second[k] == 0xffffffff
                                                     for k in ('UVD_VERSION',
                                                               'UVD_STATUS',
                                                               'UVD_POWER_STATUS')),
                                 'cold_cycle_required': True})
        finally:
            smu.close()
            emit('cleanup', {'sram_undo_attempted': False,
                             'clock_restored': False,
                             'cold_cycle_required': True})


if __name__ == '__main__':
    main()
