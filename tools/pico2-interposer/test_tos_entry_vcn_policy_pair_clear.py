#!/usr/bin/env python3
"""Execute the signed early-TOS two-policy/harvest probe as native ARM code."""

import argparse
from pathlib import Path

import unicorn as uc
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_R0

from test_tos_entry_spi_diag import ENTRY, FLASH, verify_signed_view


SELECTOR = 0x0322003c
APERTURE = 0x02f00000
P1, P2, HARVEST = (APERTURE + at for at in (0x1f820, 0x1f8a4, 0x1f81c))
ORIGINAL = {P1: 0x185103, P2: 0xb, HARVEST: 3}


def encoded(value):
    return (('flash', FLASH + 0x40000 + (value & 0xffff) * 4),
            ('flash', FLASH + 0x80000 + (value >> 16) * 4))


def run_case(trial, mode):
    arm = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    arm.mem_map(0, 0x20000)
    arm.mem_write(0, trial[ENTRY:ENTRY + 0x14000])
    arm.mem_map(FLASH, 0x100000)
    arm.mem_map(SELECTOR & ~0xfff, 0x1000)
    arm.mem_map(APERTURE, 0x100000)
    for at, value in ORIGINAL.items():
        arm.mem_write(at, (0 if mode == 'guard-fail' and at == P1 else value).to_bytes(4, 'little'))
    arm.reg_write(UC_ARM_REG_R0, 1)
    arm.reg_write(UC_ARM_REG_LR, 0x12345678)
    events, visits, writes = [], [], {at: [] for at in ORIGINAL}

    def on_code(machine, pc, size, unused):
        if pc in (0, 0x5c00, 0x98, 0x190, 0x5d2c):
            visits.append(pc)
        if pc in (0x190, 0x5d2c):
            machine.emu_stop()

    def on_read(machine, access, at, size, value, unused):
        if at in ORIGINAL:
            if mode == 'policy-ignored' and at in (P1, P2) and writes[at]:
                machine.mem_write(at, ORIGINAL[at].to_bytes(4, 'little'))
            if mode in ('harvest-ignored', 'policy-ignored') and at == HARVEST and writes[at]:
                machine.mem_write(HARVEST, (3).to_bytes(4, 'little'))
            if mode == 'restore-fail' and at == P2 and len(writes[P2]) == 2:
                machine.mem_write(P2, (0).to_bytes(4, 'little'))
            events.append(('read', at, int.from_bytes(machine.mem_read(at, 4), 'little')))
        elif FLASH <= at < FLASH + 0x100000:
            events.append(('flash', at))

    def on_write(machine, access, at, size, value, unused):
        if at == SELECTOR:
            events.append(('selector', value))
        elif at in ORIGINAL:
            writes[at].append(value)
            events.append(('write', at, value))
        elif FLASH <= at < FLASH + 0x100000 or APERTURE <= at < APERTURE + 0x100000:
            raise AssertionError(f'unexpected protected write {at:#x}')

    arm.hook_add(uc.UC_HOOK_CODE, on_code)
    arm.hook_add(uc.UC_HOOK_MEM_READ, on_read)
    arm.hook_add(uc.UC_HOOK_MEM_WRITE, on_write)
    arm.emu_start(0, 0x200, timeout=1000000, count=2500)

    def rd(at, value):
        return [('selector', (at - APERTURE) >> 4), ('read', at, value)]

    def wr(at, value):
        return [('selector', (at - APERTURE) >> 4), ('write', at, value)]

    expected = [('flash', FLASH + 0x3fffc)]
    if mode == 'guard-fail':
        expected += rd(P1, 0) + [('flash', FLASH + 0x3ffe0)]
        assert visits == [0, 0x5c00, 0x98, 0x190]
    else:
        after_p1 = ORIGINAL[P1] if mode == 'policy-ignored' else 0
        after_p2 = ORIGINAL[P2] if mode == 'policy-ignored' else 0
        after_harvest = 3 if mode in ('harvest-ignored', 'policy-ignored') else 0
        after_p2_restore = 0 if mode == 'restore-fail' else ORIGINAL[P2]
        expected += (rd(P1, ORIGINAL[P1]) + rd(P2, ORIGINAL[P2]) +
                     rd(HARVEST, 3) + [('flash', FLASH + 0x3fff8)] +
                     wr(P1, 0) + rd(P1, after_p1) + list(encoded(after_p1)) +
                     wr(P2, 0) + rd(P2, after_p2) + list(encoded(after_p2)) +
                     wr(HARVEST, 0) + rd(HARVEST, after_harvest) +
                     list(encoded(after_harvest)))
        if after_harvest == 0:
            expected += wr(HARVEST, 3) + rd(HARVEST, 3) + list(encoded(3))
        expected += (wr(P2, ORIGINAL[P2]) + rd(P2, after_p2_restore) +
                     list(encoded(after_p2_restore)))
        if mode == 'restore-fail':
            expected += [('flash', FLASH + 0x3ffec)]
            assert visits == [0, 0x5c00, 0x5d2c]
        else:
            expected += (wr(P1, ORIGINAL[P1]) + rd(P1, ORIGINAL[P1]) +
                         list(encoded(ORIGINAL[P1])) + [('flash', FLASH + 0x3fff0)])
            assert visits == [0, 0x5c00, 0x98, 0x190]
            for at, value in ORIGINAL.items():
                assert int.from_bytes(arm.mem_read(at, 4), 'little') == value
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
    assert 0 < len(component) <= 512
    trial = args.trial.read_bytes()
    verify_signed_view(args.clean.read_bytes(), trial, component)
    for mode in ('harvest-ignored', 'harvest-accepted', 'policy-ignored',
                 'guard-fail', 'restore-fail'):
        run_case(trial, mode)
    print('PASS: five native ARM policy/harvest cases, guard and restore halt')


if __name__ == '__main__':
    main()
