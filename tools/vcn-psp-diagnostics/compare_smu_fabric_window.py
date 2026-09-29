#!/usr/bin/env python3
"""Compare BC250 SMU-window and host-SMN views of the VCN fabric gate.

Run on the BC250 from the pinned current boot. Only mailbox reads and PCI
SMN-index selections are issued; no target register or flash is written.
The GPU governor is paused to avoid racing its SMU mailbox traffic.
"""

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys

sys.path.insert(0, '/var/tmp/bc250-smu-vcn')
from bc250_smu import Bc250Smu


ROOT_CONFIG = Path('/sys/bus/pci/devices/0000:00:00.0/config')
GPU_CONFIG = Path('/sys/bus/pci/devices/0000:01:00.0/config')
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
GOVERNOR = 'cyan-skillfish-governor-smu'
CONTROLS = ((0x5a870, 0xff), (0x6d0f8, 2), (0x6d190, 0x01010101))
TARGET = 0x50d6c


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(path, expected):
    with path.open('rb', buffering=0) as stream:
        value, = struct.unpack('<I', stream.read(4))
    require(value == expected, f'{path}: unexpected PCI identity {value:#010x}')


def root_smn_read(fd, address):
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        require(os.pwrite(fd, struct.pack('<I', address), 0xb8) == 4,
                'incomplete SMN index write')
        raw = os.pread(fd, 4, 0xbc)
        require(len(raw) == 4, 'incomplete SMN data read')
        return struct.unpack('<I', raw)[0]
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-boot-id', required=True)
    args = parser.parse_args()
    require(os.geteuid() == 0, 'root required')
    require(BOOT_ID.read_text().strip() == args.expected_boot_id,
            'boot ID changed')
    identity(ROOT_CONFIG, 0x13e01022)
    identity(GPU_CONFIG, 0x13fe1002)
    def interrupted(signum, frame):
        raise InterruptedError(f'signal {signum}')
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    was_active = subprocess.run(['systemctl', 'is-active', '--quiet', GOVERNOR]).returncode == 0
    require(was_active, 'GPU governor not active before diagnostic')
    subprocess.run(['systemctl', 'stop', GOVERNOR], check=True, timeout=15)
    smu = None
    alive = False
    try:
        smu = Bc250Smu(timeout=2)
        require(smu.alive(), 'SMU test message failed')
        require(int.from_bytes(smu.smu_read(0x7b3c), 'little') == 0,
                'secure SMU debug path is closed')
        fd = os.open(ROOT_CONFIG, os.O_RDWR | os.O_CLOEXEC)
        try:
            observations = {}
            for address, expected in CONTROLS:
                host = root_smn_read(fd, address)
                status, window = smu.sec_smn_read32(address)
                observations[f'{address:#x}'] = {'host': f'{host:#010x}',
                                                   'smu_window': f'{window:#010x}',
                                                   'status': f'{status:#x}'}
                require(host == expected and status == 1 and window == expected,
                        f'control mismatch at {address:#x}; target not attempted')
            host = root_smn_read(fd, TARGET)
            require(host == 0xf0, f'unexpected host target baseline {host:#x}')
            status, window = smu.sec_smn_read32(TARGET)
            observations[f'{TARGET:#x}'] = {'host': f'{host:#010x}',
                                             'smu_window': f'{window:#010x}',
                                             'status': f'{status:#x}'}
            print(json.dumps({'boot_id': args.expected_boot_id,
                              'observations': observations,
                              'target_writes': False}, sort_keys=True), flush=True)
        finally:
            os.close(fd)
        alive = smu.alive()
        require(alive, 'SMU stopped responding')
    finally:
        if smu is not None:
            try:
                if not alive:
                    alive = smu.alive()
            finally:
                smu.close()
        if alive:
            subprocess.run(['systemctl', 'start', GOVERNOR], check=True, timeout=15)


if __name__ == '__main__':
    main()
