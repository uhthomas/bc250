#!/usr/bin/env python3
"""Read pinned BC250 SMN words through the root PCI index/data window.

Run as root on the BC250. This writes only the PCI SMN *index* register to
select each address; it never writes any target. Readouts after a failed
VCN probe do not establish what happened during earlier boot firmware stages.
"""

import fcntl
import argparse
import json
import os
from pathlib import Path
import struct


ROOT_CONFIG = Path('/sys/bus/pci/devices/0000:00:00.0/config')
GPU_CONFIG = Path('/sys/bus/pci/devices/0000:01:00.0/config')
ROOT_ID = 0x13e01022
GPU_ID = 0x13fe1002
SMN_INDEX, SMN_DATA = 0xb8, 0xbc
ADDRESSES = (0x50d6c, 0x511b4)
CORE_MASK_CONTROL = 0x5a870
DOM6_POWER = (0x6d0f8, 0x6d17c, 0x6d184, 0x6d190)


def identity(path, expected):
    with path.open('rb', buffering=0) as stream:
        actual, = struct.unpack('<I', stream.read(4))
    if actual != expected:
        raise RuntimeError(f'{path}: PCI identity {actual:#010x} != {expected:#010x}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-mask-control', action='store_true',
                        help='also read the previously measured 0x5a870 SMN word')
    parser.add_argument('--dom6-power', action='store_true',
                        help='also read the VCN-domain gate, request, rail and status words')
    args = parser.parse_args()
    identity(ROOT_CONFIG, ROOT_ID)
    identity(GPU_CONFIG, GPU_ID)
    fd = os.open(ROOT_CONFIG, os.O_RDWR | os.O_CLOEXEC)
    values = {}
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            addresses = (ADDRESSES +
                         ((CORE_MASK_CONTROL,) if args.core_mask_control else ()) +
                         (DOM6_POWER if args.dom6_power else ()))
            for address in addresses:
                count = os.pwrite(fd, struct.pack('<I', address), SMN_INDEX)
                raw = os.pread(fd, 4, SMN_DATA)
                if count != 4 or len(raw) != 4:
                    raise RuntimeError(f'incomplete PCI config access at {address:#x}')
                value, = struct.unpack('<I', raw)
                values[f'{address:#x}'] = f'{value:#010x}'
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
    print(json.dumps({
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'values': values,
        'target_writes': False,
    }, sort_keys=True))


if __name__ == '__main__':
    main()
