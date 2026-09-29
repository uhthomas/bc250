#!/usr/bin/env python3
"""Read the live BC250 VCN SMU state after a diagnostic module attempt.

This only reads SMU SRAM/SMN and local boot/module state. It is intended to
decide whether a second module trial can reuse the same native VCLK setup.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct

from bc250_smu import Bc250Smu
import trial_smu_clock_walker as clock


BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
GPU = Path('/sys/bus/pci/devices/0000:01:00.0')
SOURCE = clock.SOURCE
SOURCE_SHA = clock.SOURCE_SHA
ENABLES = (0x6d108, 0x6d130, 0x6d158)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-boot-id', required=True)
    args = parser.parse_args()
    require(BOOT_ID.read_text().strip() == args.expected_boot_id,
            'boot ID changed')
    require((GPU/'vendor').read_text().strip() == '0x1002' and
            (GPU/'device').read_text().strip() == '0x13fe',
            'wrong GPU')
    source = SOURCE.read_bytes()
    require(hashlib.sha256(source).hexdigest() == SOURCE_SHA,
            'SMU source hash changed')
    smu = Bc250Smu(timeout=2)
    try:
        require(smu.alive() and smu._get_smu_version() == (1, 0x00580600),
                'SMU not live or version changed')
        require(clock.word(smu, 0x7b3c) == 0 and
                clock.word(smu, 0x746c + 8 * (0x1d - 1)) == 0x2e6c8,
                'SMU debug window or VCN clock handler changed')
        for start, size in ((0x2e448, 0x140), (0x2e6c8, 0x60),
                            (0x2362c, 0x200)):
            require(clock.read(smu, start, size) == source[start:start+size],
                    f'SMU code changed at {start:#x}')
        require((clock.word(smu, 0x181e0), clock.word(smu, 0x181e4)) ==
                (clock.BASE, clock.BASE + 20 * 12),
                'SMU clock table pointers changed')
        table = clock.read(smu, clock.BASE, clock.TABLE_SIZE)
        record = clock.read(smu, clock.SLOT_RECORD, 28)
        u32 = clock.u32
        target = 15
        observed = {
            'boot_id': args.expected_boot_id,
            'smu_source_sha256': SOURCE_SHA,
            'table_sha256': hashlib.sha256(table).hexdigest(),
            'generation': [u32(table, 0), u32(table, 4)],
            'slot': u32(table, 8 + 4 * target),
            'requested_word': f'{u32(table, 0x14c + 12 * target):#010x}',
            'applied_word': f'{u32(table, 0x5c + 12 * target):#010x}',
            'slot_code': record[2],
            'remembered_code': record[6],
            'hardware_code': clock.smn(smu, clock.CLOCK_SMN),
            'slot_enables': [clock.smn(smu, address) for address in ENABLES],
            'domain_control': clock.smn(smu, 0x6d0f8),
            'domain_status': clock.smn(smu, 0x6d190),
            'domain_power_command': clock.smn(smu, 0x6d17c),
            'domain_power_rail': clock.smn(smu, 0x6d184),
            'amdgpu_module_loaded': Path('/sys/module/amdgpu').exists(),
            'gpu_driver_bound': (GPU/'driver').exists(),
        }
        observed['vclk_mhz_from_applied_word'] = struct.unpack(
            '<f', struct.pack('<I', u32(table, 0x5c + 12 * target)))[0]
        require(observed['slot'] == 0x17, 'VCN target slot changed')
        print(json.dumps(observed, sort_keys=True))
    finally:
        smu.close()


if __name__ == '__main__':
    main()
