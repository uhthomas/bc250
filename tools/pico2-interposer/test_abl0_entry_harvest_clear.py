#!/usr/bin/env python3
"""Execute the guarded ABL0 harvest write against synthetic PSP MMIO."""

import argparse
import hashlib
from pathlib import Path
import struct
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import unicorn as uc
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R12, UC_ARM_REG_SP,
)


ABL_STARTS = (0x99F700, 0x99FC00, 0x9ABB00, 0x9AFB00, 0x9B9D00)
SELECTOR = 0x0322003C
APERTURE = 0x02F1F81C
FLASH = 0x27C40000


def run_case(trial: bytes, abl0_body: bytes, sample: int, ignored: bool) -> None:
    machine = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    machine.mem_map(0x54000, 0x2000)
    machine.mem_write(0x54000, trial[ABL_STARTS[0]:ABL_STARTS[0] + 0x100])
    machine.mem_write(0x54100, abl0_body)
    machine.mem_map(0x70000, 0x4000)
    machine.mem_map(SELECTOR & ~0xFFF, 0x1000)
    machine.mem_map(APERTURE & ~0xFFFFF, 0x100000)
    machine.mem_write(APERTURE, struct.pack("<I", sample))
    machine.mem_map(FLASH, 0x40000)
    machine.reg_write(UC_ARM_REG_R0, 0x11223344)
    machine.reg_write(UC_ARM_REG_R1, 0x55667788)
    machine.reg_write(UC_ARM_REG_R12, 0xAABBCCDD)
    machine.reg_write(UC_ARM_REG_LR, 0x543210)
    machine.reg_write(UC_ARM_REG_SP, 0x71234)
    visits, reads, writes = [], [], []

    def on_code(model, address, size, unused):
        visits.append(address)
        if address == 0x54104:
            model.emu_stop()

    def on_read(model, access, address, size, value, unused):
        if address == APERTURE:
            if ignored and any(item[0] == APERTURE for item in writes):
                model.mem_write(APERTURE, struct.pack("<I", sample))
            reads.append((address, size))
        elif FLASH <= address < FLASH + 0x40000:
            reads.append((address, size))

    def on_write(model, access, address, size, value, unused):
        if address in (SELECTOR, APERTURE):
            writes.append((address, size, value))

    machine.hook_add(uc.UC_HOOK_CODE, on_code)
    machine.hook_add(uc.UC_HOOK_MEM_READ, on_read)
    machine.hook_add(uc.UC_HOOK_MEM_WRITE, on_write)
    machine.emu_start(0x54100, 0x56000, timeout=1000000, count=50)
    post = 0 if sample == 3 and not ignored else sample
    expected_flash = FLASH + ((post & 0xFFFF) << 2)
    assert visits[0] == 0x54100 and 0x54070 in visits and 0x540A4 in visits and visits[-1] == 0x54104, visits
    assert writes == [(SELECTOR, 4, 0x1F81)] + ([(APERTURE, 4, 0)] if sample == 3 else []), writes
    assert reads == [(APERTURE, 4), (APERTURE, 4), (expected_flash, 4)], reads
    assert machine.reg_read(UC_ARM_REG_PC) == 0x54104
    assert machine.reg_read(UC_ARM_REG_SP) == 0x72000
    assert machine.reg_read(UC_ARM_REG_R0) == 0x11223344
    assert machine.reg_read(UC_ARM_REG_R1) == 0x55667788
    assert machine.reg_read(UC_ARM_REG_R12) == 0xAABBCCDD
    assert machine.reg_read(UC_ARM_REG_LR) == 0x543210


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    args = parser.parse_args()
    clean = args.clean.read_bytes()
    trial = args.trial.read_bytes()
    key = serialization.load_pem_private_key(args.private_key.read_bytes(), None)
    public = key.public_key()
    assert trial[0x9DB290:0x9DB390] == public.public_numbers().n.to_bytes(256, "little")
    assert trial[ABL_STARTS[0] + 0xA0:ABL_STARTS[0] + 0xA4] == clean[ABL_STARTS[0] + 0xA0:ABL_STARTS[0] + 0xA4]
    for index, start in enumerate(ABL_STARTS):
        body_size = struct.unpack_from("<I", trial, start + 0x14)[0]
        compressed_size = struct.unpack_from("<I", trial, start + 0x54)[0]
        body = zlib.decompress(trial[start + 0x100:start + 0x100 + compressed_size])
        assert hashlib.sha256(body).digest() == trial[start + 0xD0:start + 0xF0]
        signed_end = start + 0x100 + body_size
        public.verify(trial[signed_end:signed_end + 0x100], trial[start:signed_end],
                      padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                      hashes.SHA256())
        if index == 0:
            abl0_body = body
    for sample, ignored in ((3, False), (3, True), (2, False),
                            (0, False), (0x10003, False), (0xFFFFFFFF, False)):
        run_case(trial, abl0_body, sample, ignored)
    print("PASS: six guarded ARM cases; accepted/ignored writes; five signed ABL views")


if __name__ == "__main__":
    main()
