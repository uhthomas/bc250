#!/usr/bin/env python3
"""Execute the ABL0 read-only harvest hook against synthetic PSP MMIO."""

import argparse
import hashlib
from pathlib import Path
import struct
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import unicorn as uc
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4,
    UC_ARM_REG_R12, UC_ARM_REG_SP,
)


ABL_STARTS = (0x99F700, 0x99FC00, 0x9ABB00, 0x9AFB00, 0x9B9D00)
SELECTOR = 0x0322003C
FLASH = 0x27C40000


def run_case(trial: bytes, body: bytes, sample: int, smn_address: int,
             abl_index: int, runtime_base: int) -> None:
    aperture = 0x02F00000 | smn_address
    machine = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    machine.mem_map(runtime_base, 0x1C000)
    machine.mem_write(runtime_base, trial[ABL_STARTS[abl_index]:ABL_STARTS[abl_index] + 0x100])
    machine.mem_write(runtime_base + 0x100, body)
    stack = 0xB1234 if abl_index else 0x71234
    machine.mem_map(stack & ~0xFFF, 0x4000)
    machine.mem_map(SELECTOR & ~0xFFF, 0x1000)
    if abl_index:
        machine.mem_write(SELECTOR, struct.pack("<I", 0x1357))
    machine.mem_map(aperture & ~0xFFFFF, 0x100000)
    machine.mem_write(aperture, struct.pack("<I", sample))
    machine.mem_map(FLASH, 0x40000)
    for address in (FLASH, FLASH + 4, FLASH + 8, FLASH + 12,
                    FLASH + 0x1E0, FLASH + 0x3FFFC):
        machine.mem_write(address, struct.pack("<I", address))
    machine.reg_write(UC_ARM_REG_R0, 0x11223344)
    machine.reg_write(UC_ARM_REG_R1, 0x55667788)
    machine.reg_write(UC_ARM_REG_R4, 0x1234ABCD)
    machine.reg_write(UC_ARM_REG_R12, 0xAABBCCDD)
    machine.reg_write(UC_ARM_REG_LR, 0x543210)
    machine.reg_write(UC_ARM_REG_SP, stack)
    visits, reads, writes = [], [], []

    def on_code(model, address, size, unused):
        visits.append(address)
        if address == runtime_base + 0x104:
            model.emu_stop()

    def on_read(model, access, address, size, value, unused):
        if aperture <= address < aperture + 4 or FLASH <= address < FLASH + 0x40000:
            reads.append((address, size))

    def on_write(model, access, address, size, value, unused):
        if address == SELECTOR:
            writes.append((address, size, value))

    machine.hook_add(uc.UC_HOOK_CODE, on_code)
    machine.hook_add(uc.UC_HOOK_MEM_READ, on_read)
    machine.hook_add(uc.UC_HOOK_MEM_WRITE, on_write)
    machine.emu_start(runtime_base + 0x100, runtime_base + 0x2000,
                      timeout=1000000, count=40)
    expected_flash = FLASH + (sample & 0xFFFF) * 4
    assert visits[0] == runtime_base + 0x100 and runtime_base + 0x70 in visits and \
        runtime_base + 0xA4 in visits and visits[-1] == runtime_base + 0x104, visits
    expected_writes = [(SELECTOR, 4, smn_address >> 4)]
    if abl_index:
        expected_writes.append((SELECTOR, 4, 0x1357))
    assert writes == expected_writes, writes
    if abl_index:
        assert machine.mem_read(SELECTOR, 4) == struct.pack("<I", 0x1357)
    assert reads == [(aperture, 4), (expected_flash, 4)], reads
    assert machine.reg_read(UC_ARM_REG_PC) == runtime_base + 0x104
    assert machine.reg_read(UC_ARM_REG_SP) == (0x72000 if abl_index == 0 else stack - 8)
    assert machine.reg_read(UC_ARM_REG_R0) == 0x11223344
    assert machine.reg_read(UC_ARM_REG_R1) == 0x55667788
    assert machine.reg_read(UC_ARM_REG_R12) == 0xAABBCCDD
    assert machine.reg_read(UC_ARM_REG_LR) == 0x543210
    if abl_index:
        assert machine.mem_read(stack - 8, 8) == struct.pack("<II", 0x1234ABCD, 0x543210)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--smn-address", type=lambda value: int(value, 0),
                        default=0x1F81C)
    parser.add_argument("--abl-index", type=int, choices=range(5), default=0)
    args = parser.parse_args()
    if args.smn_address not in (0x1F81C, 0x1F820, 0x1F8A4, 0x50D6C):
        parser.error("only the four pinned hook targets are supported")
    clean = args.clean.read_bytes()
    trial = args.trial.read_bytes()
    key = serialization.load_pem_private_key(args.private_key.read_bytes(), None)
    public = key.public_key()
    assert trial[0x9DB290:0x9DB390] == public.public_numbers().n.to_bytes(256, "little")
    selected = ABL_STARTS[args.abl_index]
    assert trial[selected + 0xA0:selected + 0xA4] == clean[selected + 0xA0:selected + 0xA4]
    for index, start in enumerate(ABL_STARTS):
        body_size = struct.unpack_from("<I", trial, start + 0x14)[0]
        compressed_size = struct.unpack_from("<I", trial, start + 0x54)[0]
        body = zlib.decompress(trial[start + 0x100:start + 0x100 + compressed_size])
        assert hashlib.sha256(body).digest() == trial[start + 0xD0:start + 0xF0]
        signed_end = start + 0x100 + body_size
        public.verify(trial[signed_end:signed_end + 0x100], trial[start:signed_end],
                      padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                      hashes.SHA256())
        if index == args.abl_index:
            selected_body = body
    for runtime_base in ((0x54000, 0x84000) if args.abl_index else (0x54000,)):
        for sample in (0, 1, 2, 3, 0xFFFFFFFF, 0x12345678):
            run_case(trial, selected_body, sample, args.smn_address,
                     args.abl_index, runtime_base)
    print(f"PASS: six ARM MMIO/SPI cases; five signed ABL views; ABL{args.abl_index} header marker preserved")


if __name__ == "__main__":
    main()
