#!/usr/bin/env python3
"""Execute the signed three-register TOS-entry read hook as native ARM code."""

import argparse
from pathlib import Path

import unicorn as uc
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_R0

from test_tos_entry_spi_diag import ENTRY, FLASH, verify_signed_view


SELECTOR = 0x0322003c
APERTURE = 0x02f00000
TARGETS = (0x1f820, 0x1f8a4, 0x1f81c)
MARKERS = (0x3fffc, 0x3fff8, 0x3fff4, 0x3fff0)


def run_case(trial, samples, targets=TARGETS):
    arm = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    arm.mem_map(0, 0x20000)
    arm.mem_write(0, trial[ENTRY:ENTRY + 0x14000])
    arm.mem_map(FLASH, 0x100000)
    arm.mem_map(SELECTOR & ~0xfff, 0x1000)
    arm.mem_map(APERTURE, 0x100000)
    # The direct PSP aperture selects the high address bits separately; its
    # local data window uses only the low 20 bits of the requested SMN word.
    assert all(target % 4 == 0 for target in targets)
    assert len({target & 0xfffff for target in targets}) == len(targets)
    for target, sample in zip(targets, samples):
        arm.mem_write(APERTURE + (target & 0xfffff), sample.to_bytes(4, 'little'))
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
        elif (FLASH <= at < FLASH + 0x100000 or
              APERTURE <= at < APERTURE + 0x100000):
            raise AssertionError(f'unexpected protected write {at:#x}')

    arm.hook_add(uc.UC_HOOK_CODE, on_code)
    arm.hook_add(uc.UC_HOOK_MEM_READ, on_read)
    arm.hook_add(uc.UC_HOOK_MEM_WRITE, on_write)
    arm.emu_start(0, 0x200, timeout=1000000, count=2000)

    expected = [('flash', FLASH + MARKERS[0], 4)]
    for i, (target, sample) in enumerate(zip(targets, samples)):
        expected += [
            ('selector', target >> 4, 4),
            ('aperture', APERTURE + (target & 0xfffff), 4),
            ('flash', FLASH + 0x40000 + (sample & 0xffff) * 4, 4),
            ('flash', FLASH + 0x80000 + (sample >> 16) * 4, 4),
            ('flash', FLASH + MARKERS[i + 1], 4),
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
    parser.add_argument('--targets', nargs=3, type=lambda value: int(value, 0),
                        default=TARGETS)
    args = parser.parse_args()
    component = args.component.read_bytes()
    for target in args.targets:
        assert target.to_bytes(4, 'little') in component
    trial = args.trial.read_bytes()
    verify_signed_view(args.clean.read_bytes(), trial, component)
    for samples in ((0x185103, 0xb, 3), (0, 0, 0),
                    (0xffffffff, 0xffffffff, 0xffffffff)):
        run_case(trial, samples, args.targets)
    print('PASS: three native ARM read cases; signed ROM view verified')


if __name__ == '__main__':
    main()
