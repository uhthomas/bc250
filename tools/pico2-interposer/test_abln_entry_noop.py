#!/usr/bin/env python3
"""Verify the signed ABL1 no-op detour and its displaced entry instruction."""

import argparse
from pathlib import Path
import hashlib
import struct
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_CPSR, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0,
    UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4,
    UC_ARM_REG_R12, UC_ARM_REG_SP,
)

ABL_STARTS = (0x99F700, 0x99FC00, 0x9ABB00, 0x9AFB00, 0x9B9D00)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    args = parser.parse_args()
    clean, trial = args.clean.read_bytes(), args.trial.read_bytes()
    key = serialization.load_pem_private_key(args.private_key.read_bytes(), None)
    assert trial[0x9DB290:0x9DB390] == key.public_key().public_numbers().n.to_bytes(256, "little")
    selected = ABL_STARTS[1]
    assert trial[selected + 0x94:selected + 0xD0] == clean[selected + 0x94:selected + 0xD0]
    for index, start in enumerate(ABL_STARTS):
        body_size = struct.unpack_from("<I", trial, start + 0x14)[0]
        compressed_size = struct.unpack_from("<I", trial, start + 0x54)[0]
        body = zlib.decompress(trial[start + 0x100:start + 0x100 + compressed_size])
        assert hashlib.sha256(body).digest() == trial[start + 0xD0:start + 0xF0]
        signed_end = start + 0x100 + body_size
        key.public_key().verify(trial[signed_end:signed_end + 0x100], trial[start:signed_end],
                                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                                hashes.SHA256())
        if index == 1:
            selected_body = body
    for base in (0x54000, 0x64000):
        for flags in (0, 0x20000000, 0x80000000):
            model = Uc(UC_ARCH_ARM, UC_MODE_ARM)
            model.mem_map(base, 0x1C000)
            model.mem_map(0x90000, 0x4000)
            model.mem_write(base, trial[selected:selected + 0x100])
            model.mem_write(base + 0x100, selected_body)
            registers = {
                UC_ARM_REG_R0: 0x11223344, UC_ARM_REG_R1: 0x55667788,
                UC_ARM_REG_R2: 0x99AABBCC, UC_ARM_REG_R3: 0x12344321,
                UC_ARM_REG_R4: 0x1234ABCD, UC_ARM_REG_R12: 0xAABBCCDD,
                UC_ARM_REG_LR: 0x543210, UC_ARM_REG_SP: 0x91234,
            }
            for register, value in registers.items():
                model.reg_write(register, value)
            model.reg_write(UC_ARM_REG_CPSR, (model.reg_read(UC_ARM_REG_CPSR) & ~0xF0000000) | flags)
            initial_flags = model.reg_read(UC_ARM_REG_CPSR) & 0xF0000000
            visits = []

            def on_code(machine, address, size, unused):
                visits.append(address)
                if address == base + 0x104:
                    machine.emu_stop()

            model.hook_add(UC_HOOK_CODE, on_code)
            model.emu_start(base + 0x100, base + 0x2000, count=20)
            assert visits == [base + 0x100, base + 0x70, base + 0x74, base + 0x104], visits
            assert model.reg_read(UC_ARM_REG_PC) == base + 0x104
            assert model.reg_read(UC_ARM_REG_SP) == 0x9122C
            assert model.mem_read(0x9122C, 8) == struct.pack("<II", 0x1234ABCD, 0x543210)
            assert model.reg_read(UC_ARM_REG_CPSR) & 0xF0000000 == initial_flags
            for register, value in registers.items():
                if register != UC_ARM_REG_SP:
                    assert model.reg_read(register) == value, register
    print("PASS: ABL1 no-op detour preserves registers, flags, and stack; five signed ABL views")


if __name__ == "__main__":
    main()
