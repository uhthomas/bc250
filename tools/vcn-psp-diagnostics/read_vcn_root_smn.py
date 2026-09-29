#!/usr/bin/env python3
"""Read BC250 VCN register byte addresses through the root PCI SMN window.

Only the root PCI SMN index is changed, then restored. No VCN target register,
firmware, BIOS EEPROM, or Pico flash is written. The addresses equal
(Cyan Skillfish UVD0 segment 1 0x7e00 + VCN 2.0 register dword offset) * 4.
Do not run on the BC250: both a timed read during VCN startup and a later
idle-boot read stalled the board on 2026-09-29 and required PDU cold cycles.
The root PCI SMN path is not a validated route for these VCN registers.
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
    'vcn_pgfsm_status': 0x0001f804,
    'vcn_harvesting': 0x0001f81c,
    'vcn_soft_reset': 0x00020180,
    'vcn_status': 0x000201bc,
    'vcn_version': 0x00020f24,
    'vcn_cache_bar_low': 0x0002107c,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def identity(path: Path, expected: int) -> None:
    with path.open('rb', buffering=0) as stream:
        raw = stream.read(4)
    require(len(raw) == 4, f'{path}: short PCI identity')
    actual, = struct.unpack('<I', raw)
    require(actual == expected, f'{path}: PCI identity {actual:#010x}')


def read_smn(fd: int, address: int) -> int:
    require(os.pwrite(fd, struct.pack('<I', address), SMN_INDEX) == 4,
            f'incomplete SMN index write for {address:#x}')
    raw = os.pread(fd, 4, SMN_DATA)
    require(len(raw) == 4, f'incomplete SMN data read for {address:#x}')
    return struct.unpack('<I', raw)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-boot-id', required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    require(os.geteuid() == 0, 'root is required for PCI config access')
    boot_id = BOOT_ID.read_text().strip()
    require(boot_id == args.expected_boot_id, 'BC250 boot changed')
    identity(ROOT_CONFIG, ROOT_ID)
    identity(GPU_CONFIG, GPU_ID)

    fd = os.open(ROOT_CONFIG, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        original = os.pread(fd, 4, SMN_INDEX)
        require(len(original) == 4, 'incomplete original SMN index read')
        try:
            sweeps = [
                {label: read_smn(fd, address)
                 for label, address in ADDRESSES.items()}
                for _ in range(2)
            ]
        finally:
            require(os.pwrite(fd, original, SMN_INDEX) == 4,
                    'failed to restore SMN index')
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    require(BOOT_ID.read_text().strip() == boot_id,
            'BC250 boot changed during read')
    require(all(sweep['gfx_clock_control'] not in (0, 0xffffffff)
                for sweep in sweeps), 'known live GFX clock control did not respond')
    result = {
        'boot_id': boot_id,
        'addresses': {label: f'{value:#010x}'
                      for label, value in ADDRESSES.items()},
        'sweeps': [{label: f'{value:#010x}' for label, value in sweep.items()}
                   for sweep in sweeps],
        'target_writes': False,
        'smn_index_restored': True,
    }
    if args.output:
        args.output.write_text(json.dumps(result, sort_keys=True) + '\n')
        print(json.dumps({'boot_id': boot_id, 'samples': len(sweeps),
                          'output': str(args.output), 'target_writes': False},
                         sort_keys=True))
    else:
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
