#!/usr/bin/env python3
"""Verify 4-KiB IPL address encoding and the signed trial image."""
import argparse
from pathlib import Path

import unicorn as uc
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_R0

from test_tos_entry_spi_diag import ENTRY, FLASH, verify_signed_view


def run_slice(trial, offset, halfwords, marked=False):
    arm = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    if offset < 0x20000:
        low_end = (max(0x20000, offset + halfwords * 2) + 0xfff) & ~0xfff
        arm.mem_map(0, low_end)
    else:
        arm.mem_map(0, 0x20000)
        source_start = offset & ~0xfff
        source_end = (offset + halfwords * 2 + 0xfff) & ~0xfff
        arm.mem_map(source_start, source_end - source_start)
    arm.mem_write(0, trial[ENTRY:ENTRY + 0x14000])
    arm.mem_map(FLASH, 0x100000)
    samples = [(i * 109 + 7) & 0xffff for i in range(halfwords)]
    arm.mem_write(offset, b''.join(sample.to_bytes(2, 'little') for sample in samples))
    # The cave is executable even if the source range straddles 0x5c00.
    arm.mem_write(0x5c00, trial[ENTRY + 0x5c00:ENTRY + 0x5c00 + 0x200])
    source = bytes(arm.mem_read(offset, halfwords * 2))
    samples = [int.from_bytes(source[i:i + 2], 'little')
               for i in range(0, len(source), 2)]
    arm.reg_write(UC_ARM_REG_R0, 1)
    arm.reg_write(UC_ARM_REG_LR, 0x12345678)
    reads, visits = [], []

    def stop_at_stock(machine, address, size, unused):
        if address == 0x98:
            visits.append(address)
            machine.emu_stop()

    def flash_read(machine, access, address, size, value, unused):
        if FLASH <= address < FLASH + 0x100000:
            reads.append((address, size))

    arm.hook_add(uc.UC_HOOK_CODE, stop_at_stock)
    arm.hook_add(uc.UC_HOOK_MEM_READ, flash_read)
    arm.emu_start(0x5c00, 0x20000, timeout=8000000, count=250000)
    expected = [(FLASH + sample * 4, 4) for sample in samples]
    if marked:
        expected = ([(FLASH + address, 4) for address in (0x3fffc, 0x3fff8, 0x3fff4)] +
                    expected +
                    [(FLASH + address, 4) for address in (0x3fff0, 0x3ffec, 0x3ffe8)])
    assert reads == expected
    assert visits == [0x98]
    assert arm.reg_read(UC_ARM_REG_R0) == 1
    assert arm.reg_read(UC_ARM_REG_LR) == 0x12345678


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', type=Path, required=True)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--component', type=Path, required=True)
    parser.add_argument('--offset', type=lambda value: int(value, 0), default=0)
    parser.add_argument('--halfwords', type=int, default=2048)
    parser.add_argument('--marked', action='store_true')
    args = parser.parse_args()
    trial = args.trial.read_bytes()
    verify_signed_view(args.clean.read_bytes(), trial, args.component.read_bytes())
    assert args.offset % 2 == 0 and 0 < args.halfwords <= 32768
    run_slice(trial, args.offset, args.halfwords, args.marked)
    print(f'PASS: {args.halfwords} encoded IPL halfwords, original reset return and signed views')


if __name__ == '__main__':
    main()
