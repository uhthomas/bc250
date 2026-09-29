#!/usr/bin/env python3
"""Execute the guarded TOS-entry fabric trial in native ARM emulation."""

import argparse
from pathlib import Path

import unicorn as uc
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_R0

from test_tos_entry_spi_diag import ENTRY, FLASH, verify_signed_view


SELECTOR = 0x0322003C
APERTURE = 0x02F00000
FABRIC = APERTURE + 0x50D6C
CORE_MASK = APERTURE + 0x5A870
HARVEST = APERTURE + 0x1F81C
ORIGINAL, CANDIDATE = 0xF0, 0x8F0


def encoded(value):
    return [('flash', FLASH + 0x40000 + (value & 0xffff) * 4),
            ('flash', FLASH + 0x80000 + (value >> 16) * 4)]


def run_case(trial, mode):
    arm = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    arm.mem_map(0, 0x20000)
    arm.mem_write(0, trial[ENTRY:ENTRY + 0x14000])
    arm.mem_map(FLASH, 0x100000)
    arm.mem_map(SELECTOR & ~0xfff, 0x1000)
    arm.mem_map(APERTURE, 0x100000)
    arm.mem_write(FABRIC, (0 if mode == 'guard-fail' else ORIGINAL).to_bytes(4, 'little'))
    arm.mem_write(CORE_MASK, (0x77).to_bytes(4, 'little'))
    arm.mem_write(HARVEST, (3).to_bytes(4, 'little'))
    arm.reg_write(UC_ARM_REG_R0, 1)
    arm.reg_write(UC_ARM_REG_LR, 0x12345678)
    events, visits, writes = [], [], []

    def on_code(machine, pc, size, unused):
        if pc in (0, 0x5c00, 0x98, 0x190):
            visits.append(pc)
        if pc == 0x190:
            machine.emu_stop()

    def on_read(machine, access, at, size, value, unused):
        if at == FABRIC and writes:
            if mode == 'ignored':
                machine.mem_write(FABRIC, ORIGINAL.to_bytes(4, 'little'))
            elif mode == 'restore-fail' and len(writes) == 2:
                machine.mem_write(FABRIC, CANDIDATE.to_bytes(4, 'little'))
        if FLASH <= at < FLASH + 0x100000:
            events.append(('flash', at))
            if at == FLASH + 0x3ffec:
                machine.emu_stop()
        elif at in (FABRIC, CORE_MASK, HARVEST):
            events.append(('read', at))

    def on_write(machine, access, at, size, value, unused):
        if at == SELECTOR:
            events.append(('selector', value))
        elif at == FABRIC:
            writes.append(value)
            events.append(('write', at, value))
        elif FLASH <= at < FLASH + 0x100000 or APERTURE <= at < APERTURE + 0x100000:
            raise AssertionError(f'unexpected protected write {at:#x}')

    arm.hook_add(uc.UC_HOOK_CODE, on_code)
    arm.hook_add(uc.UC_HOOK_MEM_READ, on_read)
    arm.hook_add(uc.UC_HOOK_MEM_WRITE, on_write)
    arm.emu_start(0, 0x200, timeout=1000000, count=3000)

    marker = lambda offset: ('flash', FLASH + offset)
    read = lambda address: [('selector', (address - APERTURE) >> 4), ('read', address)]
    write = lambda address, value: [('selector', (address - APERTURE) >> 4),
                                    ('write', address, value)]
    if mode == 'guard-fail':
        expected = [marker(0x3fffc), *read(FABRIC), marker(0x3ffe0)]
        assert writes == []
    else:
        after_set = ORIGINAL if mode == 'ignored' else CANDIDATE
        after_restore = CANDIDATE if mode == 'restore-fail' else ORIGINAL
        expected = [marker(0x3fffc), *read(FABRIC), *read(CORE_MASK),
                    *read(HARVEST), marker(0x3fff8),
                    *write(FABRIC, CANDIDATE), *read(FABRIC),
                    *encoded(after_set), *read(HARVEST), *encoded(3),
                    *write(FABRIC, ORIGINAL), *read(FABRIC),
                    *encoded(after_restore)]
        if mode == 'restore-fail':
            expected += [marker(0x3ffec)]
        else:
            expected += [*read(HARVEST), *encoded(3), marker(0x3fff0)]
        assert writes == [CANDIDATE, ORIGINAL]
    assert events == expected, (mode, events, expected)
    if mode == 'restore-fail':
        assert visits == [0, 0x5c00]
    else:
        assert visits == [0, 0x5c00, 0x98, 0x190]
        assert arm.reg_read(UC_ARM_REG_R0) == 1
        assert arm.reg_read(UC_ARM_REG_LR) == 0x12345678


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', type=Path, required=True)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--component', type=Path, required=True)
    args = parser.parse_args()
    component = args.component.read_bytes()
    assert len(component) <= 512
    trial = args.trial.read_bytes()
    verify_signed_view(args.clean.read_bytes(), trial, component)
    for mode in ('accepted', 'ignored', 'guard-fail', 'restore-fail'):
        run_case(trial, mode)
    print('PASS: accepted, ignored, guard-fail, restore-fail; signed ROM view')


if __name__ == '__main__':
    main()
