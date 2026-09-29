#!/usr/bin/env python3
"""Read BC250 VCN clock-enable state through the root PCI SMN window.

Only the PCI SMN index register is written. No target SMN register, firmware,
or flash device is modified. Use --expected-boot-id to avoid mixing boots.
The 0x0116f200 meaning comes from the Van Gogh SMU and is a hypothesis on
BC250; its readback alone cannot prove that the VCN clock oscillates.
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
SMN_INDEX = 0xb8
SMN_DATA = 0xbc
ADDRESSES = {
    'gfx_clock_control': 0x0115a820,
    'vcn_clock_enable_candidate': 0x0116f200,
    'vcn_clock_code': 0x0006d128,
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(path, expected):
    with path.open('rb', buffering=0) as stream:
        value, = struct.unpack('<I', stream.read(4))
    require(value == expected, f'{path}: PCI identity {value:#010x}')


def read_smn(fd, address):
    require(os.pwrite(fd, struct.pack('<I', address), SMN_INDEX) == 4,
            f'incomplete SMN index write for {address:#x}')
    raw = os.pread(fd, 4, SMN_DATA)
    require(len(raw) == 4, f'incomplete SMN data read for {address:#x}')
    return struct.unpack('<I', raw)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-boot-id', required=True)
    args = parser.parse_args()
    require(os.geteuid() == 0, 'root is required for PCI config access')
    boot_id = BOOT_ID.read_text().strip()
    require(boot_id == args.expected_boot_id, 'BC250 boot changed')
    identity(ROOT_CONFIG, ROOT_ID)
    identity(GPU_CONFIG, GPU_ID)

    fd = os.open(ROOT_CONFIG, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        first = {label: read_smn(fd, address)
                 for label, address in ADDRESSES.items()}
        second = {label: read_smn(fd, address)
                  for label, address in ADDRESSES.items()}
        require(first == second, 'SMN readbacks changed between sweeps')
        require(first['gfx_clock_control'] not in (0, 0xffffffff),
                'known live GFX clock control did not respond')
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    require(BOOT_ID.read_text().strip() == boot_id, 'BC250 boot changed during read')
    print(json.dumps({'boot_id': boot_id,
                      'values': {key: f'{value:#010x}'
                                 for key, value in first.items()},
                      'target_writes': False}, sort_keys=True))


if __name__ == '__main__':
    main()
