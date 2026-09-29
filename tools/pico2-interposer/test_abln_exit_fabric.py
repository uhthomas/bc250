#!/usr/bin/env python3
"""Execute the signed ABL3 exit probe at two simulated PSP load addresses."""

import argparse
import hashlib
from pathlib import Path
import struct
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (
    UC_ARM_REG_CPSR, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0,
    UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4,
    UC_ARM_REG_R12, UC_ARM_REG_SP,
)

ABL_STARTS = (0x99F700, 0x99FC00, 0x9ABB00, 0x9AFB00, 0x9B9D00)
SELECTOR = 0x0322003C
FLASH = 0x27C40000


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
    selected = ABL_STARTS[3]
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
        if index == 3:
            selected_body = body
    original_size = struct.unpack_from("<I", clean, selected + 0x54)[0]
    original_body = zlib.decompress(clean[selected + 0x100:selected + 0x100 + original_size])
    assert selected_body[:0x0C] == original_body[:0x0C]
    assert original_body[0x0C:0x10] == bytes.fromhex("1080bde8")
    assert selected_body[0x0C:0x10] != original_body[0x0C:0x10]

    for base in (0x54000, 0x84000):
        for sample in (0, 1, 2, 3, 0xC0, 0xF0, 0xFFFFFFFF):
            model = Uc(UC_ARCH_ARM, UC_MODE_ARM)
            model.mem_map(base, 0x1C000)
            model.mem_map(0xB1000, 0x4000)
            model.mem_map(SELECTOR & ~0xFFF, 0x1000)
            aperture = 0x02F00000 | 0x50D6C
            model.mem_map(aperture & ~0xFFFFF, 0x100000)
            model.mem_map(FLASH, 0x40000)
            model.mem_write(base, trial[selected:selected + 0x100])
            model.mem_write(base + 0x100, selected_body)
            model.mem_write(SELECTOR, struct.pack("<I", 0x1357))
            model.mem_write(aperture, struct.pack("<I", sample))
            flash_read = FLASH + (sample & 0xFFFF) * 4
            model.mem_write(flash_read, struct.pack("<I", 0x12345678))
            registers = {
                UC_ARM_REG_R0: 0x11223344, UC_ARM_REG_R1: 0x55667788,
                UC_ARM_REG_R2: 0x99AABBCC, UC_ARM_REG_R3: 0x12344321,
                UC_ARM_REG_R4: 0xBADACAFE, UC_ARM_REG_R12: 0xAABBCCDD,
                UC_ARM_REG_LR: 0x543210,
            }
            for register, value in registers.items():
                model.reg_write(register, value)
            model.reg_write(UC_ARM_REG_SP, 0xB122C)
            model.mem_write(0xB122C, struct.pack("<II", registers[UC_ARM_REG_R4], base + 0x200))
            visits, reads, writes = [], [], []

            def on_code(machine, address, size, unused):
                visits.append(address)
                if address == base + 0x200:
                    machine.emu_stop()

            def on_read(machine, access, address, size, value, unused):
                if aperture <= address < aperture + 4 or FLASH <= address < FLASH + 0x40000:
                    reads.append((address, size))

            def on_write(machine, access, address, size, value, unused):
                if address == SELECTOR:
                    writes.append(value)

            model.hook_add(UC_HOOK_CODE, on_code)
            model.hook_add(UC_HOOK_MEM_READ, on_read)
            model.hook_add(UC_HOOK_MEM_WRITE, on_write)
            model.emu_start(base + 0x10C, base + 0x1000, count=40)
            assert visits[0] == base + 0x10C and base + 0x70 in visits and \
                base + 0xA4 in visits and visits[-1] == base + 0x200, visits
            assert reads == [(aperture, 4), (flash_read, 4)], reads
            assert writes == [0x50D6C >> 4, 0x1357], writes
            assert model.mem_read(SELECTOR, 4) == struct.pack("<I", 0x1357)
            assert model.reg_read(UC_ARM_REG_PC) == base + 0x200
            assert model.reg_read(UC_ARM_REG_SP) == 0xB1234
            for register, value in registers.items():
                assert model.reg_read(register) == value, register
    print("PASS: 14 ABL3-exit MMIO/SPI cases; relocated return; five signed ABL views")


if __name__ == "__main__":
    main()
