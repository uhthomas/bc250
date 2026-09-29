#!/usr/bin/env python3
"""Execute the RAM-only fabric-word probe's actual Thumb instructions offline.

The SVC hooks are a model of service results, not proof of BC250 write access.
The test checks that every path either avoids the write or attempts the exact
0xF0 restore before returning, and identifies the unavoidable restore-failure
case that requires a cold cycle.
"""

import hashlib
from pathlib import Path
import struct

import unicorn as uc
from unicorn.arm_const import (
    UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_SP,
)


ROOT = Path(__file__).resolve().parents[2]
CAVE = ROOT / 'output/pico2/psp-50d6c-read-20260928/fabric-bit-probe.bin'
CAVE_SHA = '042fe4b5b5d5ba03a4fbeaf22f575804ace0ae5d082ffada8df1c9c8750ead7b'
BASE, ENTRY, STOP, STACK = 0xe00000, 0xe17c54, 0xe0fd48, 0x20000000
TARGET = 0x50d6c


def run(cave, initial=0xf0, accept=True, errors=None, forced_after=None):
    errors = errors or {}
    machine = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB)
    machine.mem_map(BASE, 0x20000)
    machine.mem_write(ENTRY, cave)
    machine.mem_map(STACK, 0x10000)
    machine.reg_write(UC_ARM_REG_SP, STACK + 0x8000)
    state, events = initial, []
    completed = False

    def code(mu, pc, _size, _data):
        nonlocal completed
        if pc == STOP:
            completed = True
            mu.emu_stop()

    def interrupt(mu, number, _data):
        nonlocal state
        assert number == 2
        pc = mu.reg_read(UC_ARM_REG_PC)
        opcode = bytes(mu.mem_read(pc-2, 2))
        assert mu.reg_read(UC_ARM_REG_R0) == TARGET
        assert mu.reg_read(UC_ARM_REG_R2) == 4
        if opcode == bytes.fromhex('7bdf'):
            n = sum(event[0] == 'read' for event in events)
            status = errors.get(('read', n), 0)
            if not status:
                mu.mem_write(mu.reg_read(UC_ARM_REG_R1), struct.pack('<I', state))
            events.append(('read', state, status))
        elif opcode == bytes.fromhex('7cdf'):
            value = mu.reg_read(UC_ARM_REG_R1)
            assert value in (0x8f0, 0xf0)
            n = sum(event[0] == 'write' for event in events)
            status = errors.get(('write', n), 0)
            if not status and accept:
                state = forced_after if value == 0x8f0 and forced_after is not None else value
            events.append(('write', value, status))
        else:
            raise AssertionError(f'unexpected SVC at {pc-2:#x}: {opcode.hex()}')
        mu.reg_write(UC_ARM_REG_R0, status)

    machine.hook_add(uc.UC_HOOK_CODE, code)
    machine.hook_add(uc.UC_HOOK_INTR, interrupt)
    machine.emu_start(ENTRY | 1, STOP+2, timeout=1_000_000, count=2_000)
    assert completed
    assert machine.reg_read(UC_ARM_REG_SP) == STACK + 0x8000
    return machine.reg_read(UC_ARM_REG_R0), state, events


def main():
    cave = CAVE.read_bytes()
    assert len(cave) == 124 and hashlib.sha256(cave).hexdigest() == CAVE_SHA
    result, state, events = run(cave)
    assert (result, state) == (0x700008f0, 0xf0)
    assert [event[0] for event in events] == ['read', 'write', 'read', 'write', 'read']
    assert [event[1] for event in events if event[0] == 'write'] == [0x8f0, 0xf0]
    assert run(cave, accept=False)[:2] == (0x700000f0, 0xf0)
    assert run(cave, initial=0x123)[:2] == (0x70000123, 0x123)
    assert run(cave, errors={('read', 0): 9})[:2] == (9, 0xf0)
    result, state, events = run(cave, errors={('write', 0): 0xffff0004})
    assert (result, state) == (0xffff0004, 0xf0)
    assert [event[1] for event in events if event[0] == 'write'] == [0x8f0, 0xf0]
    assert run(cave, errors={('read', 1): 0xffff0005})[:2] == (0xffff0005, 0xf0)
    assert run(cave, errors={('write', 1): 0xffff0006})[:2] == (0x7f000000, 0x8f0)
    assert run(cave, errors={('read', 2): 0xffff0007})[:2] == (0x7f000000, 0xf0)
    assert run(cave, forced_after=0x123)[:2] == (0x70000123, 0xf0)
    print('PASS: 9 native-instruction cases, guarded write and restore sequence')


if __name__ == '__main__':
    main()
