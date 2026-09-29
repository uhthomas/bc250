#!/usr/bin/env python3
"""Execute the guarded early-TOS policy toggle against modeled SMN behavior."""

import argparse
from pathlib import Path

import unicorn as uc
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_R0

from test_tos_entry_spi_diag import ENTRY, FLASH, verify_signed_view


SELECTOR = 0x0322003c
APERTURE = 0x02f00000
POLICY = APERTURE + 0x1f820
NEIGHBOR = APERTURE + 0x1f8a4
HARVEST = APERTURE + 0x1f81c
ORIGINAL = 0x00185103


def enc(value):
    return (FLASH + 0x40000 + (value & 0xffff) * 4,
            FLASH + 0x80000 + (value >> 16) * 4)


def run_case(trial, mode):
    arm = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    arm.mem_map(0, 0x20000)
    arm.mem_write(0, trial[ENTRY:ENTRY + 0x14000])
    arm.mem_map(FLASH, 0x100000)
    arm.mem_map(SELECTOR & ~0xfff, 0x1000)
    arm.mem_map(APERTURE, 0x100000)
    arm.mem_write(POLICY, (0 if mode == 'guard-fail' else ORIGINAL).to_bytes(4, 'little'))
    arm.mem_write(NEIGHBOR, (0xb).to_bytes(4, 'little'))
    arm.mem_write(HARVEST, (3).to_bytes(4, 'little'))
    arm.reg_write(UC_ARM_REG_R0, 1)
    arm.reg_write(UC_ARM_REG_LR, 0x12345678)
    events, visits, policy_writes = [], [], []

    def on_code(machine, pc, size, unused):
        if pc in (0, 0x5c00, 0x98, 0x190, 0x5cb4):
            visits.append(pc)
        if pc in (0x190, 0x5cb4):
            machine.emu_stop()

    def on_read(machine, access, at, size, value, unused):
        if at == POLICY and policy_writes:
            if mode == 'ignored':
                machine.mem_write(POLICY, ORIGINAL.to_bytes(4, 'little'))
            elif mode == 'restore-fail' and len(policy_writes) == 2:
                machine.mem_write(POLICY, (0).to_bytes(4, 'little'))
        if FLASH <= at < FLASH + 0x100000:
            events.append(('flash', at))
        elif at in (POLICY, NEIGHBOR, HARVEST):
            events.append(('read', at))

    def on_write(machine, access, at, size, value, unused):
        if at == SELECTOR:
            events.append(('selector', value))
        elif at == POLICY:
            policy_writes.append(value)
            events.append(('write', at, value))
        elif FLASH <= at < FLASH + 0x100000 or APERTURE <= at < APERTURE + 0x100000:
            raise AssertionError(f'unexpected protected write {at:#x}')

    arm.hook_add(uc.UC_HOOK_CODE, on_code)
    arm.hook_add(uc.UC_HOOK_MEM_READ, on_read)
    arm.hook_add(uc.UC_HOOK_MEM_WRITE, on_write)
    arm.emu_start(0, 0x200, timeout=1000000, count=2000)

    marker = lambda offset: ('flash', FLASH + offset)
    read = lambda address: [('selector', (address - APERTURE) >> 4), ('read', address)]
    write = lambda address, value: [('selector', (address - APERTURE) >> 4),
                                    ('write', address, value)]
    if mode == 'guard-fail':
        expected = [marker(0x3fffc), *read(POLICY), marker(0x3ffe0)]
        assert policy_writes == []
        assert visits == [0, 0x5c00, 0x98, 0x190]
    else:
        after_clear = ORIGINAL if mode == 'ignored' else 0
        after_restore = 0 if mode == 'restore-fail' else ORIGINAL
        expected = [marker(0x3fffc), *read(POLICY), *read(NEIGHBOR),
                    *read(HARVEST), marker(0x3fff8),
                    *write(POLICY, 0), *read(POLICY),
                    marker(enc(after_clear)[0] - FLASH),
                    marker(enc(after_clear)[1] - FLASH),
                    *read(HARVEST), marker(enc(3)[0] - FLASH),
                    marker(enc(3)[1] - FLASH),
                    *write(POLICY, ORIGINAL), *read(POLICY),
                    marker(enc(after_restore)[0] - FLASH),
                    marker(enc(after_restore)[1] - FLASH),
                    marker(0x3ffec if mode == 'restore-fail' else 0x3fff0)]
        assert policy_writes == [0, ORIGINAL]
        assert visits == ([0, 0x5c00, 0x5cb4] if mode == 'restore-fail'
                          else [0, 0x5c00, 0x98, 0x190])
        assert int.from_bytes(arm.mem_read(POLICY, 4), 'little') == after_restore
    assert events == expected, (mode, events, expected)
    if mode != 'restore-fail':
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
    print('PASS: accepted, ignored, guard-fail and restore-fail native ARM cases')


if __name__ == '__main__':
    main()
