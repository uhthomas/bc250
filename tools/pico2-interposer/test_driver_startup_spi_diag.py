#!/usr/bin/env python3
"""Execute the signed PSP-driver startup SPI diagnostic as native Thumb code."""
import argparse
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import unicorn as uc
from unicorn.arm_const import (UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0,
                               UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP)

DRIVER, DRIVER_LEN, TOS, TOS_LEN = 0x984f00, 0x1a770, 0x8eac00, 0x14350
HOOK, CAVE, ORIGINAL = 0xe09622, 0xe17d00, 0xe09890
FLASH = 0x27c00000


def verify_signed_view(clean, trial, hook, cave):
    assert len(clean) == len(trial) == 0x1000000
    assert trial[DRIVER + 0x9622:DRIVER + 0x9626] == hook
    assert trial[DRIVER + 0x17d00:DRIVER + 0x17d00 + len(cave)] == cave
    assert trial[TOS + 0x100:TOS + TOS_LEN - 256] == clean[TOS + 0x100:TOS + TOS_LEN - 256]
    assert trial[TOS + 0xd0:TOS + 0xf0] == hashlib.sha256(
        trial[TOS + 0x100:TOS + TOS_LEN - 256]).digest()
    modulus = int.from_bytes(trial[0x9db140:0x9db240], 'little')
    public = rsa.RSAPublicNumbers(65537, modulus).public_key()
    pss = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)
    for start, length in ((TOS, TOS_LEN), (DRIVER, DRIVER_LEN)):
        public.verify(trial[start + length - 256:start + length],
                      trial[start:start + length - 256], pss, hashes.SHA256())


def run_case(trial, status, sample):
    arm = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB)
    arm.mem_map(0xe00000, 0x20000)
    arm.mem_write(0xe00000, trial[DRIVER:DRIVER + 0x20000])
    arm.mem_map(FLASH, 0x100000)
    arm.reg_write(UC_ARM_REG_SP, 0xe1f000)
    arm.reg_write(UC_ARM_REG_R0, 0x5678)
    arm.reg_write(UC_ARM_REG_LR, 0x87654321)
    visits, calls, reads = [], [], []

    def code(machine, address, size, unused):
        if address in (HOOK, CAVE, ORIGINAL, HOOK + 4):
            visits.append(address)
        if address == ORIGINAL:
            machine.reg_write(UC_ARM_REG_R0, 0x1234)
            machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))
        elif address == HOOK + 4:
            machine.emu_stop()

    def service(machine, interrupt, unused):
        calls.append((interrupt, machine.reg_read(UC_ARM_REG_R0),
                      machine.reg_read(UC_ARM_REG_R1), machine.reg_read(UC_ARM_REG_R2)))
        machine.mem_write(machine.reg_read(UC_ARM_REG_R1), sample.to_bytes(4, 'little'))
        machine.reg_write(UC_ARM_REG_R0, status)

    def flash_read(machine, access, address, size, value, unused):
        if FLASH <= address < FLASH + 0x100000:
            reads.append((address, size))

    arm.hook_add(uc.UC_HOOK_CODE, code)
    arm.hook_add(uc.UC_HOOK_INTR, service)
    arm.hook_add(uc.UC_HOOK_MEM_READ, flash_read)
    arm.emu_start(HOOK | 1, HOOK + 8, timeout=1000000, count=1000)
    expected = [(FLASH + 0x3fffc, 4)] + [
                (FLASH + lane * 0x40000 + (((word >> shift) & 0xffff) << 2), 4)
                for lane, (word, shift) in enumerate(((status, 0), (status, 16),
                                                      (sample, 0), (sample, 16)))]
    assert reads == expected, (reads, expected)
    assert calls == [(2, 0x1f81c, CAVE + 0x50, 4)]
    assert visits == [HOOK, CAVE, ORIGINAL, HOOK + 4], visits
    assert arm.reg_read(UC_ARM_REG_R0) == 0x1234
    assert arm.reg_read(UC_ARM_REG_SP) == 0xe1f000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', type=Path, required=True)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--hook', type=Path, required=True)
    parser.add_argument('--cave', type=Path, required=True)
    args = parser.parse_args()
    trial = args.trial.read_bytes()
    verify_signed_view(args.clean.read_bytes(), trial, args.hook.read_bytes(), args.cave.read_bytes())
    for status, sample in ((0, 3), (9, 0), (0x1234abcd, 0xdeadbeef)):
        run_case(trial, status, sample)
    print('PASS: 3 native Thumb startup SPI cases, signed TOS and driver views')


if __name__ == '__main__':
    main()
