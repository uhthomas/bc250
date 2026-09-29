#!/usr/bin/env python3
"""Execute the ABL0 marker branch in an ARM model and verify signed views.

This tests the intended 0x54000 package/0x54100 body mapping; the physical
ABL loader and instruction permissions remain to be checked on the board.
"""

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


ABL0 = 0x99F700
ABL_STARTS = (0x99F700, 0x99FC00, 0x9ABB00, 0x9AFB00, 0x9B9D00)
KEY_MODULUS = 0x9DB290
MARKER = 0x27C3FFFC


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    args = parser.parse_args()
    trial = args.trial.read_bytes()
    key = serialization.load_pem_private_key(args.private_key.read_bytes(), None)
    public = key.public_key()
    assert trial[KEY_MODULUS:KEY_MODULUS + 256] == public.public_numbers().n.to_bytes(256, "little")
    for index, start in enumerate(ABL_STARTS):
        body_size = struct.unpack_from("<I", trial, start + 0x14)[0]
        compressed_size = struct.unpack_from("<I", trial, start + 0x54)[0]
        compressed = trial[start + 0x100:start + 0x100 + compressed_size]
        decoded = zlib.decompress(compressed)
        assert hashlib.sha256(decoded).digest() == trial[start + 0xD0:start + 0xF0]
        signed_end = start + 0x100 + body_size
        signature = trial[signed_end:signed_end + 0x100]
        public.verify(signature, trial[start:signed_end],
                      padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                      hashes.SHA256())
        if index == 0:
            abl0_body = decoded

    machine = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    machine.mem_map(0x54000, 0x2000)
    machine.mem_write(0x54000, trial[ABL0:ABL0 + 0x100])
    machine.mem_write(0x54100, abl0_body)
    machine.mem_map(0x70000, 0x4000)
    machine.mem_map(0x27C00000, 0x40000)
    machine.mem_write(MARKER, bytes.fromhex("3412cdab"))
    machine.reg_write(UC_ARM_REG_R0, 0x11223344)
    machine.reg_write(UC_ARM_REG_R1, 0x55667788)
    machine.reg_write(UC_ARM_REG_R12, 0xAABBCCDD)
    machine.reg_write(UC_ARM_REG_LR, 0x543210)
    machine.reg_write(UC_ARM_REG_SP, 0x71234)
    visits = []
    marker_reads = []

    def on_code(model, address, size, unused):
        visits.append(address)
        if address == 0x54104:
            model.emu_stop()

    def on_read(model, access, address, size, value, unused):
        if 0x27C00000 <= address < 0x27C40000:
            marker_reads.append((address, size))

    machine.hook_add(uc.UC_HOOK_CODE, on_code)
    machine.hook_add(uc.UC_HOOK_MEM_READ, on_read)
    machine.emu_start(0x54100, 0x56000, timeout=1000000, count=30)
    assert visits == [0x54100, 0x54070, 0x54074, 0x54078, 0x5407C,
                      0x54080, 0x54084, 0x54104], visits
    assert marker_reads == [(MARKER, 4)], marker_reads
    assert machine.reg_read(UC_ARM_REG_PC) == 0x54104
    assert machine.reg_read(UC_ARM_REG_SP) == 0x72000
    assert machine.reg_read(UC_ARM_REG_R0) == 0x11223344
    assert machine.reg_read(UC_ARM_REG_R1) == 0x55667788
    assert machine.reg_read(UC_ARM_REG_R12) == 0xAABBCCDD
    assert machine.reg_read(UC_ARM_REG_LR) == 0x543210
    print("PASS: five RSA-PSS signed ABL views; one marker read; original ABL0 entry state restored")


if __name__ == "__main__":
    main()
