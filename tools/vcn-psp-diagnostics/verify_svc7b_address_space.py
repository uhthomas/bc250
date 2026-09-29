#!/usr/bin/env python3
"""Execute the pinned PSP SVC 0x7b read path in synthetic memory.

This proves which address the Trusted OS maps for the service argument. It
does not prove what hardware responds behind that mapped aperture on a BC250.
No device, firmware, or flash is accessed.
"""

import argparse
import hashlib
from pathlib import Path
import struct

import unicorn as uc
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_SP,
)


TOS = (Path(__file__).resolve().parents[2] /
       'output/video-decode-20260922/psp-analysis/PSP_FW_TRUSTED_OS.bin')
TOS_SHA256 = 'fc6459ae7833c5ba2f942904ad9c5d97aa3a069267e7344aa33934dd9536d11a'
WINDOW = 0x01000000
MAPPER_REGS = 0x03220000
CONTEXT = 0x00e50000
STACK = 0x20000000
STOP = 0x50000000
DEFAULT_ARGUMENT = 0x0001f81c
SAMPLE = 0x12345678


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', type=lambda raw: int(raw, 0),
                        default=DEFAULT_ARGUMENT,
                        help='aligned PSP service argument in the 1-MiB window')
    args = parser.parse_args()
    argument = args.address
    if argument < 0 or argument > 0xffffc or argument & 3:
        parser.error('--address must be an aligned word in 0..0xffffc')
    signed = TOS.read_bytes()
    assert hashlib.sha256(signed).hexdigest() == TOS_SHA256
    payload = signed[0x100:-0x100]
    # The read and write services dispatch to different handlers, then share
    # the page-selector mapper at payload offset 0x2fcc.
    for svc, expected in ((0x7b, 0x4d14), (0x7c, 0x4d28)):
        table = 0x45e4 + (svc - 0x51) * 4
        assert 0x45e4 + struct.unpack_from('<I', payload, table)[0] == expected

    m = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB)
    m.mem_map(0, (len(payload) + 0xfff) & ~0xfff)
    m.mem_write(0, payload)
    m.mem_map(CONTEXT, 0x10000)
    m.mem_map(STACK, 0x10000)
    m.mem_map(MAPPER_REGS, 0x1000)
    m.mem_map(WINDOW, 0x100000)
    m.mem_map(STOP, 0x1000, uc.UC_PROT_READ | uc.UC_PROT_EXEC)
    m.mem_write(0x6010, struct.pack('<I', CONTEXT))
    m.mem_write(0x6038, b'\0')
    m.mem_write(0x6054, struct.pack('<I', CONTEXT + 0x100))
    m.mem_write(0x86b0, b'\0' * 4)
    out = CONTEXT + 0x100
    m.mem_write(CONTEXT, struct.pack('<4I', argument, out, 4, 0))
    m.mem_write(WINDOW + argument, struct.pack('<I', SAMPLE))
    for reg, value in ((UC_ARM_REG_R0, 0), (UC_ARM_REG_R1, 0x7b),
                       (UC_ARM_REG_SP, STACK + 0x8000),
                       (UC_ARM_REG_LR, STOP | 1)):
        m.reg_write(reg, value)

    calls = []
    reads = []

    def on_code(mu, pc, size, _):
        if pc in (0x4d14, 0x4d46, 0x36ca, 0x36d8, 0x2fcc, STOP):
            calls.append(pc)
        if pc == STOP:
            mu.emu_stop()

    def on_read(mu, access, address, size, value, _):
        if WINDOW <= address < WINDOW + 0x100000:
            reads.append((address, size))

    m.hook_add(uc.UC_HOOK_CODE, on_code)
    m.hook_add(uc.UC_HOOK_MEM_READ, on_read)
    m.emu_start(0x45a1, STOP + 2, timeout=1_000_000, count=20_000)
    assert calls == [0x4d14, 0x4d46, 0x36ca, 0x36d8, 0x2fcc, STOP], calls
    assert reads == [(WINDOW + argument, 4)], reads
    assert m.reg_read(UC_ARM_REG_R0) == 0
    assert struct.unpack('<I', m.mem_read(out, 4))[0] == SAMPLE
    print(f'PASS: SVC 0x7b maps argument {argument:#x} to the PSP SMN '
          f'aperture at {WINDOW + argument:#x}; this synthetic test alone '
          'cannot identify MMIO')


if __name__ == '__main__':
    main()
