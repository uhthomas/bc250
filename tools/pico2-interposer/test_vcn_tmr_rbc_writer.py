#!/usr/bin/env python3
"""Execute the RAM-only PSP TMR writer hook with native Thumb instructions.

SVC calls and the physical memory alias are explicit fixtures. This proves
hook arguments, packet bytes, cleanup, and the unmarked path, not live TMR
permissions or RBC access.
"""

import argparse
import hashlib
from pathlib import Path
import struct

import unicorn as uc
from unicorn.arm_const import (UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
                               UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP)

DRIVER = 0x984f00
DRIVER_LEN = 0x1a770
STACK = 0x20000000
MAPPING = 0x30000000
ENTRY = 0xe17c8e
RESUME = 0xe17c92
SCRATCH = 0x1f854
PACKETS = struct.pack('<16I', 0xc01d, 0x7b250001,
                      *((0x53f, 0) * 7))
DESCRIPTOR = struct.pack('<6I', 0xf4, 0x1faff000, 0x1000, 0, 0, 0xffff)


def check(driver: bytes, marked: bool, map_result: int = 0,
          release_result: int = 0, stage_marker: bool = False) -> dict:
    m = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB)
    m.mem_map(0xe00000, 0x18000, uc.UC_PROT_READ | uc.UC_PROT_EXEC)
    m.mem_map(0xe18000, 0x98000)
    m.mem_write(0xe00000, driver)
    m.mem_map(STACK, 0x10000)
    m.mem_map(MAPPING, 0x1000)
    m.mem_write(MAPPING, b'\xa5' * 0x1000)
    sp = STACK + 0x8000 - 8
    m.reg_write(UC_ARM_REG_SP, sp)
    events = []
    done = False

    def code(mu, address, size, user):
        nonlocal done
        if address == RESUME:
            done = True
            mu.emu_stop()

    def service(mu, number, user):
        assert number == 2
        pc = mu.reg_read(UC_ARM_REG_PC)
        ins = bytes(mu.mem_read(pc - 2, 2))
        assert ins[1] == 0xdf
        svc = ins[0]
        a, b, c, d = [mu.reg_read(r) for r in
                      (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]
        if svc == 0x7b:
            assert (a, c) == (SCRATCH, 4)
            assert STACK <= b <= STACK + 0x10000 - 4
            mu.mem_write(b, struct.pack('<I', 0x5a13c0df if marked else 0))
            result = 0
        elif svc == 0x89:
            assert marked
            assert bytes(mu.mem_read(a, 24)) == DESCRIPTOR
            assert (c, d) == (0xfffffff7, 0)
            assert STACK <= b <= STACK + 0x10000 - 4
            result = map_result
            if result == 0:
                mu.mem_write(b, struct.pack('<I', MAPPING))
        elif svc == 0x8a:
            assert (a, b, c, d) == (MAPPING, 0x1000, 0, 0)
            result = release_result
        elif svc == 0x7c:
            assert a == SCRATCH and c == 4
            result = 0
        else:
            raise AssertionError(f'unexpected SVC {svc:#x}')
        events.append((svc, a, b, c, d, result))
        mu.reg_write(UC_ARM_REG_R0, result)

    m.hook_add(uc.UC_HOOK_CODE, code)
    m.hook_add(uc.UC_HOOK_INTR, service)
    try:
        m.emu_start(ENTRY | 1, RESUME + 2, timeout=1000000, count=10000)
    except uc.UcError as error:
        raise AssertionError(f'PSP hook stopped at {m.reg_read(UC_ARM_REG_PC):#x}') from error
    assert done and m.reg_read(UC_ARM_REG_SP) == sp
    expected_svcs = ([0x7b] + ([0x7c] if stage_marker else []) +
                     [0x89] + ([] if map_result else [0x8a]) + [0x7c]
                     if marked else [0x7b])
    assert [event[0] for event in events] == expected_svcs, events
    if marked:
        if stage_marker:
            assert events[1][2] == 0x7a000001, events
        expected_status = (0x7e010000 | (map_result & 0xffff) if map_result else
                           0x7e000003 if release_result else 0x7a000010)
        assert events[-1][2] == expected_status, events
    assert bytes(m.mem_read(MAPPING, 64)) == (PACKETS if marked and not map_result
                                               else b'\xa5' * 64)
    assert m.reg_read(UC_ARM_REG_PC) == RESUME
    return dict(marked=marked, map_result=map_result,
                release_result=release_result, svc_count=len(events))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--stage-marker', action='store_true')
    args = parser.parse_args()
    image = args.rom.read_bytes()
    assert len(image) == 0x1000000
    driver = image[DRIVER:DRIVER + DRIVER_LEN]
    cases = [check(driver, False, stage_marker=args.stage_marker),
             check(driver, True, stage_marker=args.stage_marker),
             check(driver, True, map_result=10,
                   stage_marker=args.stage_marker),
             check(driver, True, release_result=3,
                   stage_marker=args.stage_marker)]
    print(f'PASS: {len(cases)} native PSP TMR-writer cases; '
          f'ROM SHA256 {hashlib.sha256(image).hexdigest()}')


if __name__ == '__main__':
    main()
