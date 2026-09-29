#!/usr/bin/env python3
"""Execute the guarded TOS-entry harvest write/readback in synthetic MMIO."""

import argparse
from pathlib import Path

import unicorn as uc
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_R0

from test_tos_entry_spi_diag import ENTRY, FLASH, verify_signed_view


SELECTOR = 0x0322003c
APERTURE = 0x02f1f81c


def run_case(trial, before, ignores_write):
    arm = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    arm.mem_map(0, 0x20000)
    arm.mem_write(0, trial[ENTRY:ENTRY + 0x14000])
    arm.mem_map(FLASH, 0x100000)
    arm.mem_map(SELECTOR & ~0xfff, 0x1000)
    arm.mem_map(APERTURE & ~0xfffff, 0x100000)
    arm.mem_write(APERTURE, before.to_bytes(4, 'little'))
    arm.reg_write(UC_ARM_REG_R0, 1)
    arm.reg_write(UC_ARM_REG_LR, 0x12345678)
    events, visits = [], []

    def on_code(machine, pc, size, unused):
        if pc in (0, 0x5c00, 0x98, 0x190):
            visits.append(pc)
        if pc == 0x5c60 and ignores_write:
            machine.mem_write(APERTURE, before.to_bytes(4, 'little'))
        if pc == 0x190:
            machine.emu_stop()

    def on_read(machine, access, at, size, value, unused):
        if FLASH <= at < FLASH + 0x100000:
            events.append(('flash', at))
        elif at == APERTURE:
            events.append(('read', at))

    def on_write(machine, access, at, size, value, unused):
        if at in (SELECTOR, APERTURE):
            events.append(('write', at, value))

    arm.hook_add(uc.UC_HOOK_CODE, on_code)
    arm.hook_add(uc.UC_HOOK_MEM_READ, on_read)
    arm.hook_add(uc.UC_HOOK_MEM_WRITE, on_write)
    arm.emu_start(0, 0x200, timeout=1000000, count=3000)
    after = (before if ignores_write else 0) if before == 3 else 0xfffffffe

    def word_reads(value):
        return [('flash', FLASH + 0x40000 + (value & 0xffff) * 4),
                ('flash', FLASH + 0x80000 + (value >> 16) * 4)]

    expected = [('flash', FLASH + 0x3fffc),
                ('write', SELECTOR, 0x1f81), ('read', APERTURE),
                *word_reads(before)]
    if before == 3:
        expected.extend([('write', APERTURE, 0), ('read', APERTURE)])
    expected.extend([*word_reads(after), ('flash', FLASH + 0xffffc)])
    assert events == expected, (events, expected)
    assert visits == [0, 0x5c00, 0x98, 0x190], visits
    assert arm.reg_read(UC_ARM_REG_R0) == 1
    assert arm.reg_read(UC_ARM_REG_LR) == 0x12345678


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', type=Path, required=True)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--component', type=Path, required=True)
    args = parser.parse_args()
    component = args.component.read_bytes()
    assert (0x1f81c).to_bytes(4, 'little') in component
    trial = args.trial.read_bytes()
    verify_signed_view(args.clean.read_bytes(), trial, component)
    for before, ignores_write in ((3, False), (3, True), (0, False),
                                  (1, False), (0xffffffff, False)):
        run_case(trial, before, ignores_write)
    print('PASS: five native ARM guarded-write cases; signed ROM view verified')


if __name__ == '__main__':
    main()
