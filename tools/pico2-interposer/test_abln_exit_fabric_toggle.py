#!/usr/bin/env python3
"""Check the signed, guarded ABL3-exit fabric toggle in an ARM MMIO model."""

import argparse
import hashlib
from pathlib import Path
import struct
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R12,
    UC_ARM_REG_SP,
)

ABL_STARTS = (0x99F700, 0x99FC00, 0x9ABB00, 0x9AFB00, 0x9B9D00)
SELECTOR = 0x0322003C
APERTURE = 0x02F50D6C
FLASH = 0x27C40000


def run_case(trial: bytes, body: bytes, base: int, sample: int,
             ignore_write: bool) -> None:
    machine = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    machine.mem_map(base, 0x1C000)
    machine.mem_map(0xB1000, 0x4000)
    machine.mem_map(SELECTOR & ~0xFFF, 0x1000)
    machine.mem_map(APERTURE & ~0xFFFFF, 0x100000)
    machine.mem_map(FLASH, 0x40000)
    machine.mem_write(base, trial[ABL_STARTS[3]:ABL_STARTS[3] + 0x100])
    machine.mem_write(base + 0x100, body)
    machine.mem_write(SELECTOR, struct.pack("<I", 0x1357))
    machine.mem_write(APERTURE, struct.pack("<I", sample))
    encoded = (0xF0 if ignore_write else 0x8F0) if sample == 0xF0 else 0xFFFF
    flash_read = FLASH + encoded * 4
    machine.mem_write(flash_read, struct.pack("<I", 0x12345678))
    registers = {
        UC_ARM_REG_R0: 0x11223344, UC_ARM_REG_R1: 0x55667788,
        UC_ARM_REG_R2: 0x99AABBCC, UC_ARM_REG_R3: 0x12344321,
        UC_ARM_REG_R4: 0xBADACAFE, UC_ARM_REG_R12: 0xAABBCCDD,
        UC_ARM_REG_LR: 0x543210,
    }
    for register, value in registers.items():
        machine.reg_write(register, value)
    machine.reg_write(UC_ARM_REG_SP, 0xB122C)
    machine.mem_write(0xB122C, struct.pack("<II", registers[UC_ARM_REG_R4], base + 0x200))
    visits, reads, selector_writes, aperture_writes = [], [], [], []

    def on_code(model, address, size, unused):
        visits.append(address)
        if ignore_write and address == base + 0xA4:
            model.mem_write(APERTURE, struct.pack("<I", 0xF0))
        if address == base + 0x200:
            model.emu_stop()

    def on_read(model, access, address, size, value, unused):
        if APERTURE <= address < APERTURE + 4 or FLASH <= address < FLASH + 0x40000:
            reads.append((address, size))

    def on_write(model, access, address, size, value, unused):
        if address == SELECTOR:
            selector_writes.append(value)
        if address == APERTURE:
            aperture_writes.append(value)

    machine.hook_add(UC_HOOK_CODE, on_code)
    machine.hook_add(UC_HOOK_MEM_READ, on_read)
    machine.hook_add(UC_HOOK_MEM_WRITE, on_write)
    machine.emu_start(base + 0x10C, base + 0x1000, count=50)
    assert visits[0] == base + 0x10C and base + 0x70 in visits and \
        base + 0xA4 in visits and visits[-1] == base + 0x200, visits
    assert reads == ([(APERTURE, 4)] * (2 if sample == 0xF0 else 1) +
                     [(flash_read, 4)]), reads
    assert selector_writes == [0x50D6C >> 4, 0x1357], selector_writes
    assert aperture_writes == ([0x8F0, 0xF0] if sample == 0xF0 else []), aperture_writes
    assert machine.mem_read(APERTURE, 4) == struct.pack("<I", sample)
    assert machine.mem_read(SELECTOR, 4) == struct.pack("<I", 0x1357)
    assert machine.reg_read(UC_ARM_REG_PC) == base + 0x200
    assert machine.reg_read(UC_ARM_REG_SP) == 0xB1234
    for register, value in registers.items():
        assert machine.reg_read(register) == value, register


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    args = parser.parse_args()
    clean, trial = args.clean.read_bytes(), args.trial.read_bytes()
    key = serialization.load_pem_private_key(args.private_key.read_bytes(), None)
    public = key.public_key()
    assert trial[0x9DB290:0x9DB390] == public.public_numbers().n.to_bytes(256, "little")
    start = ABL_STARTS[3]
    assert trial[start + 0xA0:start + 0xA4] == clean[start + 0xA0:start + 0xA4]
    assert trial[start + 0xF0:start + 0x100] != clean[start + 0xF0:start + 0x100]
    for index, address in enumerate(ABL_STARTS):
        body_size = struct.unpack_from("<I", trial, address + 0x14)[0]
        compressed_size = struct.unpack_from("<I", trial, address + 0x54)[0]
        body = zlib.decompress(trial[address + 0x100:address + 0x100 + compressed_size])
        assert hashlib.sha256(body).digest() == trial[address + 0xD0:address + 0xF0]
        signed_end = address + 0x100 + body_size
        public.verify(trial[signed_end:signed_end + 0x100], trial[address:signed_end],
                      padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                      hashes.SHA256())
        if index == 3:
            selected_body = body
    for base in (0x54000, 0x84000):
        for sample in (0, 1, 2, 3, 0xC0, 0xF0, 0xFFFFFFFF):
            run_case(trial, selected_body, base, sample, False)
        run_case(trial, selected_body, base, 0xF0, True)
    print("PASS: 16 guarded/ignored ARM cases; selector and fabric restored; five signed ABLs")


if __name__ == "__main__":
    main()
