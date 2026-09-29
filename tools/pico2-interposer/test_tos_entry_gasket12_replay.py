#!/usr/bin/env python3
"""Execute the signed early client-12 policy hook as real ARM instructions."""

import argparse
from pathlib import Path
import re

import unicorn as uc
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_R0

from test_tos_entry_spi_diag import ENTRY, FLASH, verify_signed_view


SELECTOR = 0x0322003c
APERTURE = 0x02f00000
DESCRIPTOR = 0x0900c9a0


def reference_rows(path: Path) -> list[tuple[int, int]]:
    text = path.read_text()
    rows = [(int(address, 16), int(value, 16)) for address, value in
            re.findall(r'\.word 0x([0-9a-f]+), 0x([0-9a-f]+)', text)]
    assert len(rows) in (51, 53)
    assert rows[0] == (0x0900c234, 0)
    assert rows[-1] == (0x0900c234, 1)
    assert dict(rows)[DESCRIPTOR] == 0x20180
    return rows


def run_case(trial: bytes, rows: list[tuple[int, int]], accepted: bool,
             emit_diagnostic: bool) -> None:
    arm = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    arm.mem_map(0, 0x20000)
    arm.mem_write(0, trial[ENTRY:ENTRY + 0x14000])
    arm.mem_map(SELECTOR & ~0xfff, 0x1000)
    arm.mem_map(APERTURE, 0x100000)
    arm.mem_map(FLASH, 0x100000)
    arm.reg_write(UC_ARM_REG_R0, 1)
    arm.reg_write(UC_ARM_REG_LR, 0x12345678)
    events, visits = [], []

    def on_code(machine, pc, size, unused):
        if pc in (0, 0x5c00, 0x98, 0x190):
            visits.append(pc)
        if pc == 0x190:
            machine.emu_stop()

    def on_read(machine, access, address, size, value, unused):
        if address == APERTURE + (DESCRIPTOR & 0xfffff):
            if not accepted:
                machine.mem_write(address, (0).to_bytes(4, 'little'))
            events.append(('read', address, size))
        elif FLASH <= address < FLASH + 0x100000:
            events.append(('flash', address, size))
        elif APERTURE <= address < APERTURE + 0x100000:
            raise AssertionError(f'unexpected aperture read {address:#x}')

    def on_write(machine, access, address, size, value, unused):
        if address == SELECTOR:
            events.append(('select', value, size))
        elif APERTURE <= address < APERTURE + 0x100000:
            events.append(('write', address, value, size))
        elif FLASH <= address < FLASH + 0x100000:
            raise AssertionError(f'unexpected flash write {address:#x}')

    arm.hook_add(uc.UC_HOOK_CODE, on_code)
    arm.hook_add(uc.UC_HOOK_MEM_READ, on_read)
    arm.hook_add(uc.UC_HOOK_MEM_WRITE, on_write)
    arm.emu_start(0, 0x200, timeout=1000000, count=1000)
    expected = []
    for address, value in rows:
        expected.extend((('select', address >> 4, 4),
                         ('write', APERTURE + (address & 0xfffff), value, 4)))
    if emit_diagnostic:
        expected.extend((('select', DESCRIPTOR >> 4, 4),
                         ('read', APERTURE + (DESCRIPTOR & 0xfffff), 4),
                         ('flash', FLASH + 0x40000 + ((0x20180 if accepted else 0) &
                                                     0xffff) * 4, 4)))
    assert events == expected, (events, expected)
    assert visits == [0, 0x5c00, 0x98, 0x190], visits
    assert arm.reg_read(UC_ARM_REG_R0) == 1
    assert arm.reg_read(UC_ARM_REG_LR) == 0x12345678


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', type=Path, required=True)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--component', type=Path, required=True)
    parser.add_argument('--reference', type=Path,
                        default=Path(__file__).with_name('gasket12-reference.inc'))
    parser.add_argument('--no-diag', action='store_true')
    args = parser.parse_args()
    component = args.component.read_bytes()
    assert len(component) <= 512 and len(component) % 4 == 0
    trial = args.trial.read_bytes()
    verify_signed_view(args.clean.read_bytes(), trial, component)
    rows = reference_rows(args.reference)
    for accepted in ((True,) if args.no_diag else (True, False)):
        run_case(trial, rows, accepted, not args.no_diag)
    print(f'PASS: {len(rows)} ordered ARM writes, signed view and no flash write')


if __name__ == '__main__':
    main()
