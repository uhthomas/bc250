#!/usr/bin/env python3
"""Volatile, guarded trial of BC250 SMU Q3 message 0x1d for VCN slot 0x17.

``handler-noop`` sends index 16 with its existing zero request while the clock
table generations match. The original ``native-clock`` trial temporarily
replaced other zero requests with the firmware's skip sentinel, advanced the
generation, and requested 1250 MHz. On this BC250, the message acknowledged
without setting VCLK and restoration stalled the SMU. That mode is now disabled
at the CLI; the implementation remains for reviewing its recorded experiment.
Neither available mode writes BIOS/Pico flash or starts the decoder.
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
import sys
import time

sys.path.insert(0, '/var/tmp/bc250-smu-vcn')
from bc250_smu import Bc250Smu
from bc250_smu.errors import SmuTimeout

BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
GPU = Path('/sys/bus/pci/devices/0000:01:00.0')
METRICS = Path('/sys/class/drm/card1/device/gpu_metrics')
GOVERNOR = 'cyan-skillfish-governor-smu'
BASE = 0x13ed4
TABLE_SIZE = 0x240
SENTINEL = 0x4f800000
SOURCE_SHA = 'b0385d7c8fbbec2aaa1ce7f635df46315847e9965f13879f7c9df9b774a0ccc0'
SOURCE = Path('/var/tmp/bc250-smu-vcn/smu-sram.bin')
CLOCK = 0x0116d128
CLOCK_SMN = 0x6d128
CONTROL_SMN = 0x6d0f8
ENABLE_SMN = 0x6d130
SLOT_RECORD = 0xf710 + 0x17 * 28 + 0x80
ARG_1250 = (16 << 16) | 1250
ARG_ZERO = 16 << 16
ZERO_INDICES = (5, 6, 7, 8, 17)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def read(smu, address, size):
    require(address % 4 == size % 4 == 0, 'unaligned SMU read')
    return b''.join(smu.smu_read(p, min(18, (address + size - p) // 4))
                    for p in range(address, address + size, 72))


def word(smu, address):
    return u32(read(smu, address, 4), 0)


def smn(smu, address):
    status, value = smu.sec_smn_read32(address)
    require(status == 1, f'SMN read rejected at {address:#x}: {status:#x}')
    return value


def metrics():
    data = METRICS.read_bytes()
    size, major, minor = struct.unpack_from('<HBB', data)
    require((major, minor) == (2, 2) and 88 <= size <= len(data),
            'unexpected GPU metrics format')
    return {'vclk_mhz': struct.unpack_from('<H', data, 84)[0],
            'dclk_mhz': struct.unpack_from('<H', data, 86)[0]}


class Trial:
    def __init__(self, smu, source, emit, require_gpu_metrics=True):
        self.smu = smu
        self.source = source
        self.emit = emit
        self.require_gpu_metrics = require_gpu_metrics
        self.saved = {}
        self.attempted = []
        self.pending = False
        self.clock_before = None
        self.record_before = None
        self.table_before = None

    def sample_metrics(self):
        # A diagnostic boot deliberately keeps amdgpu unloaded until after
        # the clock request, so its DRM gpu_metrics file does not yet exist.
        return metrics() if self.require_gpu_metrics else None

    def preflight(self):
        require(self.smu.alive(), 'SMU liveness failed')
        require(self.smu._get_smu_version() == (1, 0x00580600),
                'unexpected SMU version')
        require(word(self.smu, 0x7b3c) == 0, 'secure debug access closed')
        require(word(self.smu, 0x746c + 8 * (0x1d - 1)) == 0x2e6c8,
                'Q3 0x1d handler differs')
        for start, size in ((0x2e448, 0x140), (0x2e6c8, 0x60),
                            (0x2362c, 0x200)):
            require(read(self.smu, start, size) == self.source[start:start+size],
                    f'live SMU code mismatch at {start:#x}')
        require((word(self.smu, 0x181e0), word(self.smu, 0x181e4)) ==
                (BASE, BASE + 20 * 12), 'clock-table pointers differ')
        table = read(self.smu, BASE, TABLE_SIZE)
        self.table_before = table
        require(u32(table, 0) == u32(table, 4) == 0,
                'clock walker already has pending work')
        require([u32(table, 8 + (i - 1) * 4) for i in (11, 15, 16)] ==
                [0x18, 0x16, 0x17], 'VCN index mapping differs')
        require([i for i in range(1, 21) if
                 u32(table, 0x14c + (i-1)*12) == 0 and i != 16] ==
                list(ZERO_INDICES), 'other zero-clock requests differ')
        for index in range(1, 21):
            slot = u32(table, 8 + (index-1)*4)
            require(slot <= 0x1b, 'clock table selected an invalid slot')
            record_address = 0xf710 + slot*28 + 0x80
            record = read(self.smu, record_address, 28)
            require(record == self.source[record_address:record_address+28],
                    f'live clock record differs for index {index}')
            desired_address = BASE + 0x14c + (index-1)*12
            require(u32(table, desired_address-BASE) ==
                    u32(self.source, desired_address),
                    f'live clock request differs for index {index}')
        require(u32(table, 0x14c + 15*12) == 0 and
                u32(table, 0x5c + 15*12) == 0,
                'VCN request/applied value differs')
        require(word(self.smu, 0xf714) == 0x10101,
                'VCN domain cached power state differs')
        self.record_before = read(self.smu, SLOT_RECORD, 28)
        require(self.record_before == self.source[SLOT_RECORD:SLOT_RECORD+28],
                'VCN clock record differs from captured source')
        require((self.record_before[2], self.record_before[6]) == (0, 32),
                'VCN cached clock differs')
        self.clock_before = smn(self.smu, CLOCK_SMN)
        require(self.clock_before == 0 and
                smn(self.smu, ENABLE_SMN) == 0 and
                smn(self.smu, CONTROL_SMN) == 2,
                'VCN clock controls differ')
        observed_metrics = self.sample_metrics()
        if observed_metrics is not None:
            require(observed_metrics['vclk_mhz'] == 0,
                    'VCN clock metric already nonzero')
        self.saved = {BASE: 0, BASE+4: 0}
        for index in ZERO_INDICES + (16,):
            self.saved[BASE+0x14c+(index-1)*12] = 0
        for index in range(1, 21):
            self.saved[BASE+0x5c+(index-1)*12] = u32(
                table, 0x5c+(index-1)*12)
        for offset in range(0, 28, 4):
            self.saved[SLOT_RECORD+offset] = u32(self.record_before, offset)
        self.emit('preflight', {'clock': hex(self.clock_before),
                                'metrics': observed_metrics,
                                'table_sha256': hashlib.sha256(table).hexdigest(),
                                'slot_record': self.record_before.hex(),
                                'zero_indices': ZERO_INDICES})

    def write(self, address, value):
        require(address in self.saved, f'unlisted SRAM write {address:#x}')
        self.emit('sram_write_intent', {'address': hex(address),
                                       'value': hex(value),
                                       'undo': hex(self.saved[address])})
        self.attempted.append(address)
        self.smu.smu_write32(address, value)
        require(word(self.smu, address) == value,
                f'SRAM write did not read back at {address:#x}')

    def send(self, argument):
        self.emit('native_message_intent', {'queue': 3, 'message': '0x1d',
                                            'argument': hex(argument)})
        try:
            status, result = self.smu.send_message(3, 0x1d, [argument],
                                                   check_status=False)
        except SmuTimeout:
            self.pending = True
            self.emit('native_message_timeout', {'external_cold_cycle_needed': True})
            raise
        self.emit('native_message_result', {'status': hex(status),
                                            'result': hex(result)})
        require((status, result) == (1, argument),
                'native message did not acknowledge expected argument')

    def noop(self):
        self.send(ARG_ZERO)
        require(read(self.smu, BASE, TABLE_SIZE) == self.table_before,
                'no-op message changed clock table')
        require(read(self.smu, SLOT_RECORD, 28) == self.record_before,
                'no-op message changed VCN clock record')
        require(smn(self.smu, CLOCK_SMN) == self.clock_before,
                'no-op message changed clock register')
        self.emit('noop_verified', {'unchanged': True})

    def native(self):
        require(read(self.smu, BASE, TABLE_SIZE) == self.table_before,
                'clock table changed since preflight')
        for index in ZERO_INDICES:
            self.write(BASE+0x14c+(index-1)*12, SENTINEL)
        self.write(BASE+4, 1)
        self.send(ARG_1250)
        table = read(self.smu, BASE, TABLE_SIZE)
        record = read(self.smu, SLOT_RECORD, 28)
        hardware = smn(self.smu, CLOCK_SMN)
        self.emit('native_state', {'generation': [u32(table, 0), u32(table, 4)],
                                   'target_requested_word': hex(u32(table, 0x14c+15*12)),
                                   'target_applied_word': hex(u32(table, 0x5c+15*12)),
                                   'slot_record': record.hex(),
                                   'clock_register': hex(hardware),
                                   'slot_enable': hex(smn(self.smu, ENABLE_SMN)),
                                   'domain_control': hex(smn(self.smu, CONTROL_SMN)),
                                   'metrics': metrics()})
        require([u32(table, 0), u32(table, 4)] == [1, 1],
                'clock walker did not complete generation')
        require(hardware in (0, 16), 'unexpected VCN hardware clock code')
        self.emit('completed', {'native_clock_code': hardware,
                                'hardware_decode_tested': False})

    def restore(self):
        if not self.attempted:
            return
        require(not self.pending, 'native handler may still be running')
        require(self.smu.alive(), 'SMU not responsive for restoration')
        # While requests still have skip sentinels, reset both generation words.
        # A concurrent walker would therefore still avoid the other zero slots.
        for address in (BASE, BASE+4):
            if word(self.smu, address) != self.saved[address]:
                self.write(address, self.saved[address])
        # Restore every table word changed by the native walker or this trial.
        current = read(self.smu, BASE, TABLE_SIZE)
        for offset in range(8, TABLE_SIZE, 4):
            address = BASE + offset
            before = u32(self.table_before, offset)
            if u32(current, offset) != before:
                require(address in self.saved,
                        f'unexpected clock-table change at {address:#x}')
                self.write(address, before)
        hardware = smn(self.smu, CLOCK_SMN)
        require(hardware in (0, 16), 'unexpected VCN hardware clock during undo')
        if hardware != self.clock_before:
            self.emit('clock_restore_intent', {'address': hex(CLOCK),
                                               'value': hex(self.clock_before)})
            self.smu.smu_write32(CLOCK, self.clock_before)
            require(smn(self.smu, CLOCK_SMN) == self.clock_before,
                    'VCN clock register did not restore')
        current_record = read(self.smu, SLOT_RECORD, 28)
        for offset in range(0, 28, 4):
            if u32(current_record, offset) != u32(self.record_before, offset):
                self.write(SLOT_RECORD+offset,
                           u32(self.record_before, offset))
        require(read(self.smu, BASE, TABLE_SIZE) == self.table_before,
                'clock table did not restore')
        require(read(self.smu, SLOT_RECORD, 28) == self.record_before,
                'VCN clock record did not restore')
        require(smn(self.smu, CLOCK_SMN) == self.clock_before and
                smn(self.smu, ENABLE_SMN) == 0 and
                smn(self.smu, CONTROL_SMN) == 2,
                'VCN clock controls did not restore')
        require(self.smu.alive(), 'SMU stopped responding after restore')
        self.emit('restored', {'table': True, 'record': True,
                               'clock': True, 'metrics': metrics()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('preflight', 'handler-noop'),
                        default='preflight')
    parser.add_argument('--expected-boot-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(os.geteuid() == 0 and
            BOOT_ID.read_text().strip() == args.expected_boot_id,
            'root/boot-ID guard failed')
    require(os.uname().release == '7.2.5-200.fc44.x86_64', 'wrong kernel')
    require((GPU/'vendor').read_text().strip() == '0x1002' and
            (GPU/'device').read_text().strip() == '0x13fe', 'wrong GPU')
    require(subprocess.run(['systemctl', 'is-active', '--quiet', GOVERNOR])
            .returncode == 0, 'GPU governor is not running')
    source = SOURCE.read_bytes()
    require(hashlib.sha256(source).hexdigest() == SOURCE_SHA,
            'wrong captured SMU firmware image')
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
        emit('start', {'mode': args.mode, 'boot_id': args.expected_boot_id,
                       'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       'source_sha256': SOURCE_SHA})
        subprocess.run(['systemctl', 'stop', GOVERNOR], check=True, timeout=15)
        smu = None
        trial = None
        healthy = False
        try:
            smu = Bc250Smu(timeout=2)
            trial = Trial(smu, source, emit)
            trial.preflight()
            if args.mode == 'handler-noop':
                trial.noop()
            else:
                emit('completed', {'mode': 'preflight', 'target_writes': False})
        except BaseException as error:
            emit('error', {'detail': repr(error),
                           'pending_handler': trial.pending if trial else False})
            raise
        finally:
            try:
                if trial is not None and not trial.pending:
                    trial.restore()
                if smu is not None and not (trial and trial.pending):
                    healthy = smu.alive()
            finally:
                if smu is not None:
                    smu.close()
                if healthy:
                    subprocess.run(['systemctl', 'start', GOVERNOR],
                                   check=True, timeout=15)
                emit('cleanup', {'smu_alive': healthy,
                                 'governor_active': subprocess.run(
                                     ['systemctl', 'is-active', '--quiet', GOVERNOR])
                                     .returncode == 0})


if __name__ == '__main__':
    main()
