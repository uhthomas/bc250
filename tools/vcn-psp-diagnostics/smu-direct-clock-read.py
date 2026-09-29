#!/usr/bin/env python3
"""Read one pinned high address directly from the SMU core, then restore RAM.

Default mode is read-only preflight. Live mode installs a 72-byte, read-only
Xtensa helper in the previously audited temporary gap. It never writes the
clock register, BIOS EEPROM, Pico QSPI, or an internal PSP command.
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

ROOT = Path(__file__).resolve().parent
SOURCE_SHA = 'b0385d7c8fbbec2aaa1ce7f635df46315847e9965f13879f7c9df9b774a0ccc0'
BODY_SHA = '96a04591f18bf0e2a9d04b15ee757afd1501fbdd2e93a97c26f55cf78d598cd6'
BASE, SIZE, CODE, ENTRY = 0x230, 0xc8, 0x240, 0x776c
TARGETS = (0x0116f200, 0x01210718)
RECOVERY = 'bc250-smu-direct-clock-recovery.timer'
GOVERNOR = 'cyan-skillfish-governor-smu'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Probe:
    def __init__(self, smu, timeout_type, source, body, target, emit,
                 expected_body_sha=BODY_SHA, expected_body_size=72,
                 target_writes=False):
        self.smu = smu
        self.timeout_type = timeout_type
        self.source = source
        self.body = body
        require(target in TARGETS, 'unlisted direct-read target')
        self.target = target
        self.expected_body_sha = expected_body_sha
        self.expected_body_size = expected_body_size
        self.target_writes = target_writes
        self.emit = emit
        self.saved = {}
        self.wrote = False
        self.code_attempted = False
        self.pending = False
        self.restored = False
        self.nonce = 0x25016000

    def read(self, address, size=4):
        require(address % 4 == 0 and size % 4 == 0, 'unaligned SRAM read')
        return b''.join(self.smu.smu_read(p, min(18, (address + size - p) // 4))
                        for p in range(address, address + size, 72))

    def word(self, address):
        return int.from_bytes(self.read(address), 'little')

    def ping(self):
        self.nonce += 1
        require(self.smu.test_message(self.nonce), 'SMU liveness query failed')
        self.emit('liveness', {'nonce': hex(self.nonce)})

    def preflight(self):
        require(hashlib.sha256(self.source).hexdigest() == SOURCE_SHA and
                len(self.source) == 0x40000, 'wrong SMU image')
        require(hashlib.sha256(self.body).hexdigest() == self.expected_body_sha and
                len(self.body) == self.expected_body_size, 'wrong direct-clock helper')
        self.ping()
        require(self.smu._get_smu_version() == (1, 0x00580600), 'wrong SMU version')
        require(self.word(0x7b3c) == 0, 'secure debug gate closed')
        for address, size in ((0x100, 0x430), (0xebc, 0x154),
                              (0x22ec, 0x130), (0x30b0, 0x54),
                              (0x27cc0, 0x38)):
            data = self.read(address, size)
            require(data == self.source[address:address + size],
                    f'firmware differs at {address:#x}')
            self.emit('fingerprint', {'address': hex(address), 'size': size,
                                      'sha256': hashlib.sha256(data).hexdigest()})
        require(self.word(0x7a98) == 0x7464 and self.word(0x7a9c) == 0x7464,
                'unexpected Q3/Q4 dispatch table')
        require(self.word(0x746c) == 0x1b3a8 and
                self.word(0x17e1c) == 0x8b08, 'unexpected helper pointers')
        require(self.read(BASE, SIZE) == bytes(SIZE), 'temporary gap occupied')
        require(self.read(ENTRY, 8) == bytes(8), 'dispatch slot occupied')
        for address in [*range(BASE, BASE + SIZE, 4), ENTRY, ENTRY + 4, 0x8b08]:
            self.saved[address] = self.word(address)
        self.emit('preflight_complete', {'read_address': hex(self.target),
                                         'target_writes': self.target_writes,
                                         'saved_word_count': len(self.saved)})

    def write(self, address, value):
        require(address in self.saved, 'unlisted SMU SRAM write')
        self.emit('write_intent', {'address': hex(address), 'value': hex(value),
                                   'restore': hex(self.saved[address])})
        self.wrote = True
        self.smu.smu_write32(address, value)
        require(self.word(address) == value, f'SRAM write mismatch at {address:#x}')

    def handler(self, address, flags):
        self.write(ENTRY, 0)
        self.write(ENTRY + 4, flags)
        if address:
            self.write(ENTRY, address)

    def cache(self, helper):
        require(helper in (0x30b0, 0x30e8), 'unlisted cache helper')
        self.handler(helper, 0x8006)
        self.emit('cache_call_intent', {'helper': hex(helper), 'ack_expected': False})
        try:
            result = self.smu.send_message(3, 0x61, [0], check_status=False)
        except self.timeout_type:
            self.emit('cache_no_ack', {'helper': hex(helper)})
        else:
            raise RuntimeError(f'cache helper unexpectedly acknowledged: {result}')
        self.ping()
        require(self.word(ENTRY) == helper and self.word(ENTRY + 4) == 0x8006,
                'cache dispatch changed')

    def synchronize(self):
        self.cache(0x30b0)
        self.cache(0x30e8)

    def invoke(self, argument):
        self.emit('handler_call_intent', {'argument': hex(argument),
                                          'target_writes': self.target_writes})
        try:
            result = self.smu.send_message(3, 0x61, [argument],
                                           check_status=False)
        except self.timeout_type:
            self.pending = True
            self.emit('handler_timeout', {'argument': hex(argument),
                                           'ram_restoration_deferred': True})
            raise
        self.emit('handler_response', {'argument': hex(argument),
                                       'status': hex(result[0]),
                                       'result': hex(result[1])})
        return result

    def install(self):
        image = bytearray(SIZE)
        struct.pack_into('<I', image, 0, self.target)
        image[CODE-BASE:CODE-BASE+len(self.body)] = self.body
        self.handler(0, 0)
        self.code_attempted = True
        for offset in range(0, SIZE, 4):
            self.write(BASE + offset, struct.unpack_from('<I', image, offset)[0])
        require(self.read(BASE, SIZE) == image, 'installed image mismatch')
        self.synchronize()
        self.handler(CODE, 6)
        require(self.invoke(0x40) == (1, 0x02500016), 'signature failed')
        require(self.invoke(0x106) == (0xff, 0xffffffff), 'invalid argument accepted')
        return image

    def install_and_read(self):
        image = self.install()
        first = self.invoke(0x41)
        require(first[0] == 1, 'direct clock read rejected')
        require(self.invoke(0x40) == (1, 0x02500016), 'post-read signature failed')
        second = self.invoke(0x41)
        require(second[0] == 1, 'second direct clock read rejected')
        require(first[1] == second[1], 'direct clock read changed between samples')
        self.emit('direct_read_value', {'address': hex(self.target),
                                        'value': hex(first[1]),
                                        'samples': 2})
        require(self.read(BASE, SIZE) == image, 'helper changed during run')

    def restore(self):
        if not self.wrote:
            self.restored = True
            return
        require(not self.pending, 'refusing to restore while callback may still run')
        self.handler(0, 0)
        if self.code_attempted:
            for address in range(BASE, BASE + SIZE, 4):
                self.write(address, self.saved[address])
            self.synchronize()
        self.handler(self.saved[ENTRY], self.saved[ENTRY + 4])
        self.write(0x8b08, self.saved[0x8b08])
        for address, value in self.saved.items():
            require(self.word(address) == value,
                    f'SRAM restore mismatch at {address:#x}')
        self.ping()
        self.restored = True
        self.emit('restored', {'all_saved_words_verified': True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('preflight', 'live'), default='preflight')
    parser.add_argument('--target', type=lambda value: int(value, 0),
                        choices=TARGETS, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(os.geteuid() == 0, 'root required')
    require(os.uname().release == '7.2.5-200.fc44.x86_64', 'wrong kernel')
    gpu = Path('/sys/bus/pci/devices/0000:01:00.0')
    require((gpu/'vendor').read_text().strip() == '0x1002' and
            (gpu/'device').read_text().strip() == '0x13fe', 'wrong GPU')
    if args.mode == 'live':
        require(subprocess.run(['systemctl','is-active','--quiet',RECOVERY]).returncode == 0,
                'recovery timer required')
    source = (ROOT/'smu-sram.bin').read_bytes()
    body = (ROOT/'smu-direct-clock-probe.bin').read_bytes()
    sys.path.insert(0, str(ROOT/'bc250-smu-unlock'))
    from bc250_smu import Bc250Smu
    from bc250_smu.errors import SmuTimeout

    def interrupted(signum, frame):
        raise InterruptedError(f'signal {signum}')
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    with args.output.open('x') as evidence, open('/run/bc250-vcn-test.lock','w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def emit(event, data):
            row = {'time': time.time(), 'event': event, 'data': data}
            evidence.write(json.dumps(row) + '\n')
            evidence.flush(); os.fsync(evidence.fileno())
            print(event, json.dumps(data), flush=True)
        emit('start', {'mode': args.mode,
                       'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                       'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       'body_sha256': hashlib.sha256(body).hexdigest()})
        active = subprocess.run(['systemctl','is-active','--quiet',GOVERNOR]).returncode == 0
        smu = probe = None
        healthy = False
        try:
            if active:
                subprocess.run(['systemctl','stop',GOVERNOR],check=True,timeout=15)
            smu = Bc250Smu(timeout=1)
            probe = Probe(smu,SmuTimeout,source,body,args.target,emit)
            probe.preflight()
            if args.mode == 'live':
                probe.install_and_read()
            emit('completed', {'mode': args.mode, 'target_writes': False})
        except BaseException as error:
            emit('error', repr(error))
            raise
        finally:
            try:
                if probe is not None and not probe.pending:
                    probe.restore()
                if smu is not None and not (probe and probe.pending):
                    healthy = smu.alive()
            finally:
                if smu is not None:
                    smu.close()
                if active and healthy:
                    subprocess.run(['systemctl','start',GOVERNOR],check=True,timeout=15)
                emit('cleanup', {'smu_alive': healthy,
                                  'restored': probe.restored if probe else False,
                                  'pending': probe.pending if probe else False,
                                  'governor_active': subprocess.run(
                                      ['systemctl','is-active','--quiet',GOVERNOR]).returncode == 0})


if __name__ == '__main__':
    main()
