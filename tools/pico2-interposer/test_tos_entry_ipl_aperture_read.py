#!/usr/bin/env python3
"""Execute a signed early-TOS IPL-aperture read hook with synthetic MMIO."""

import argparse
from pathlib import Path

import unicorn as uc
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_R0

from test_tos_entry_spi_diag import ENTRY, FLASH, verify_signed_view


SELECTOR = 0x0322003c
APERTURE = 0x02f00000


def run_case(trial, address, sample):
    arm = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    arm.mem_map(0, 0x20000)
    arm.mem_write(0, trial[ENTRY:ENTRY + 0x14000])
    arm.mem_map(FLASH, 0x100000)
    arm.mem_map(SELECTOR & ~0xfff, 0x1000)
    arm.mem_map(APERTURE, 0x100000)
    arm.mem_write(APERTURE + (address & 0xfffff), sample.to_bytes(4, 'little'))
    arm.reg_write(UC_ARM_REG_R0, 1)
    arm.reg_write(UC_ARM_REG_LR, 0x12345678)
    events, visits = [], []

    def on_code(machine, pc, size, unused):
        if pc in (0, 0x5c00, 0x98, 0x190):
            visits.append(pc)
        if pc == 0x190:
            machine.emu_stop()

    def on_read(machine, access, at, size, value, unused):
        if FLASH <= at < FLASH + 0x100000:
            events.append(('flash', at, size))
        elif APERTURE <= at < APERTURE + 0x100000:
            events.append(('aperture', at, size))

    def on_write(machine, access, at, size, value, unused):
        if at == SELECTOR:
            events.append(('selector', value, size))

    arm.hook_add(uc.UC_HOOK_CODE, on_code)
    arm.hook_add(uc.UC_HOOK_MEM_READ, on_read)
    arm.hook_add(uc.UC_HOOK_MEM_WRITE, on_write)
    arm.emu_start(0, 0x200, timeout=1000000, count=2000)
    expected = [
        ('flash', FLASH + 0x3fffc, 4),
        ('selector', address >> 4, 4),
        ('aperture', APERTURE + (address & 0xfffff), 4),
        ('flash', FLASH + 0x40000 + (sample & 0xffff) * 4, 4),
        ('flash', FLASH + 0x80000 + (sample >> 16) * 4, 4),
        ('flash', FLASH + 0xffffc, 4),
    ]
    assert events == expected, (events, expected)
    assert visits == [0, 0x5c00, 0x98, 0x190], visits
    assert arm.reg_read(UC_ARM_REG_R0) == 1
    assert arm.reg_read(UC_ARM_REG_LR) == 0x12345678


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', type=Path, required=True)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--component', type=Path, required=True)
    parser.add_argument('--address', type=lambda raw: int(raw, 0), required=True)
    args = parser.parse_args()
    assert args.address in (0x5a870, 0x1f81c)
    component = args.component.read_bytes()
    assert args.address.to_bytes(4, 'little') in component
    trial = args.trial.read_bytes()
    verify_signed_view(args.clean.read_bytes(), trial, component)
    for sample in (0, 3, 0xff, 0x1234abcd, 0xffffffff):
        run_case(trial, args.address, sample)
    print('PASS: five native ARM aperture and SPI cases; signed ROM view verified')


if __name__ == '__main__':
    main()
