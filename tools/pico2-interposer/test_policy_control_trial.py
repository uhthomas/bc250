#!/usr/bin/env python3
"""Execute the original and guarded SEC_GASKET write loops offline.

The policy bytes are original. SVC #0x7c is recorded and returns modeled
success; this does not model real PSP policy acceptance or live board state.
"""
import hashlib
from pathlib import Path
import struct

import unicorn as uc
from unicorn.arm_const import (UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0,
                               UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R4,
                               UC_ARM_REG_SP)


ROOT = Path(__file__).resolve().parents[2]
CLEAN = ROOT / 'output/pico2/private-20260926/CLEAN-working-backup.rom'
TRIAL = ROOT / 'output/pico2/driver-video-skip-both-control-20260928/profile/trial-NEVER-flash.rom'
BASE, STACK, TABLE, STOP = 0xe00000, 0x20000000, 0x21000000, 0x50000000
DRIVER = 0x984f00
POLICY = 0x982000
TARGET = (0x1f820, 0x185103)


def run(driver, rows):
    machine = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB)
    for address, length in ((BASE, 0x200000), (STACK, 0x10000),
                            (TABLE, 0x10000), (STOP, 0x1000)):
        machine.mem_map(address, length)
    machine.mem_write(BASE, driver[:0x1a000])
    machine.mem_write(TABLE, b''.join(struct.pack('<II', *row) for row in rows))
    stack = STACK + 0x8000
    machine.mem_write(stack, struct.pack('<5I', len(rows), TABLE, 0, 0, STOP | 1))
    machine.reg_write(UC_ARM_REG_SP, stack)
    machine.reg_write(UC_ARM_REG_LR, STOP | 1)
    machine.reg_write(UC_ARM_REG_R4, 0)
    calls, complete = [], False

    def code(mu, pc, _size, _data):
        nonlocal complete
        if pc == STOP:
            complete = True
            mu.emu_stop()

    def interrupt(mu, number, _data):
        assert number == 2
        pc = mu.reg_read(UC_ARM_REG_PC)
        assert bytes(mu.mem_read(pc-2, 2)) == bytes.fromhex('7cdf')
        calls.append(tuple(mu.reg_read(reg) for reg in
                           (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)))
        mu.reg_write(UC_ARM_REG_R0, 0)

    machine.hook_add(uc.UC_HOOK_CODE, code)
    machine.hook_add(uc.UC_HOOK_INTR, interrupt)
    machine.emu_start(0xe022b9, STOP + 2, timeout=5000000, count=200000)
    assert complete
    return calls


def main():
    clean, trial = CLEAN.read_bytes(), TRIAL.read_bytes()
    assert hashlib.sha256(clean).hexdigest() == 'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183'
    assert hashlib.sha256(trial).hexdigest() == '08dbb3482270fad1d126999d835783171132d18a13cd44a019ac6e16926af2b4'
    assert clean[POLICY:POLICY+0x2e50] == trial[POLICY:POLICY+0x2e50]
    policy = clean[POLICY:POLICY+0x2e50]
    assert struct.unpack_from('<II', policy, 0x140) == (0x201, 1230)
    rows = list(struct.iter_unpack('<II', policy[0x148:0x148+1230*8]))
    assert rows[484] == TARGET and rows.count(TARGET) == 1
    original = run(clean[DRIVER:], rows)
    guarded = run(trial[DRIVER:], rows)
    assert original == [(address, value, 4) for address, value in rows]
    assert guarded == [(address, value, 4) for index, (address, value) in enumerate(rows)
                       if index != 484]
    for fixture in ([(0x1f820, 0x185102)], [(0x1f824, 0x185103)],
                    [(0x1f820, 0x185103), (0x1f824, 0x185103)]):
        expected = [(address, value, 4) for address, value in fixture
                    if (address, value) != TARGET]
        assert run(trial[DRIVER:], fixture) == expected
    print('PASS: original 1230 writes, guarded 1229 writes, and 3 predicate controls')


if __name__ == '__main__':
    main()
