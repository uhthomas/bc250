#!/usr/bin/env python3
"""One guarded, volatile root-SMN bit-11 test on a DF-lock-omission boot.

This does not write either SPI flash. The caller must supply the boot ID of
the deliberately interposed boot; that ID is checked before touching PCI.
Only root SMN 0x50d6c is written, then immediately restored. A PDU cold cycle
may still be required if the fabric transaction stalls the host.
"""

import argparse
import fcntl
import json
import os
from pathlib import Path
import struct


ROOT_CONFIG = Path('/sys/bus/pci/devices/0000:00:00.0/config')
GPU_CONFIG = Path('/sys/bus/pci/devices/0000:01:00.0/config')
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
ROOT_ID = 0x13e01022
GPU_ID = 0x13fe1002
INDEX = 0xb8
DATA = 0xbc
GATE = 0x50d6c
CONTROL = 0x5a870
BASELINE = 0x000000f0
CORE_MASK = 0x000000ff
TRIAL = BASELINE | (1 << 11)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(path, expected):
    with path.open('rb', buffering=0) as stream:
        raw = stream.read(4)
    require(len(raw) == 4, f'incomplete PCI identity: {path}')
    actual, = struct.unpack('<I', raw)
    require(actual == expected, f'unexpected PCI identity: {path}: {actual:#010x}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-boot-id', required=True)
    args = parser.parse_args()
    boot_id = BOOT_ID.read_text().strip()
    require(boot_id == args.expected_boot_id, 'boot ID changed; refusing probe')
    identity(ROOT_CONFIG, ROOT_ID)
    identity(GPU_CONFIG, GPU_ID)

    fd = os.open(ROOT_CONFIG, os.O_RDWR | os.O_CLOEXEC)
    result = {'boot_id': boot_id, 'address': hex(GATE),
              'trial_value': hex(TRIAL), 'bios_flash_writes': False}

    def select(address):
        require(os.pwrite(fd, struct.pack('<I', address), INDEX) == 4,
                'short SMN index write')

    def read(address):
        select(address)
        raw = os.pread(fd, 4, DATA)
        require(len(raw) == 4, 'short SMN data read')
        return struct.unpack('<I', raw)[0]

    def write(address, value):
        select(address)
        require(os.pwrite(fd, struct.pack('<I', value), DATA) == 4,
                'short SMN data write')

    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        control = read(CONTROL)
        before = read(GATE)
        result.update(control=hex(control), before=hex(before))
        require(control == CORE_MASK and before == BASELINE,
                'unexpected baseline; refusing target write')
        require(BOOT_ID.read_text().strip() == boot_id,
                'boot ID changed during preflight')
        attempted = False
        try:
            attempted = True
            write(GATE, TRIAL)
            result['after_trial'] = hex(read(GATE))
        finally:
            if attempted:
                write(GATE, BASELINE)
                result['after_restore'] = hex(read(GATE))
        require(result['after_restore'] == hex(BASELINE),
                'restore readback differs from baseline; cold-cycle now')
        print(json.dumps(result, sort_keys=True))
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


if __name__ == '__main__':
    main()
