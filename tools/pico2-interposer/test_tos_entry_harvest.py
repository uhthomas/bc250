#!/usr/bin/env python3
"""Model the pre-copy TOS harvest guard and verify its signed ROM views."""
import argparse
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import unicorn as uc
from unicorn.arm_const import (UC_ARM_REG_LR, UC_ARM_REG_R0,
                               UC_ARM_REG_R1, UC_ARM_REG_R2)

TOS, TOS_LEN = 0x8eac00, 0x14350
DRIVER, DRIVER_LEN = 0x984f00, 0x1a770
KEY, ENTRY, CAVE = 0x9db140, TOS + 0x100, TOS + 0x100 + 0x5c00


def verify_signed_view(clean, trial, expected):
    assert len(clean) == len(trial) == 0x1000000
    assert trial[ENTRY:ENTRY + 4] == bytes.fromhex('fe1600ea')
    assert trial[ENTRY + 0x178:ENTRY + 0x17c] == clean[ENTRY + 0x178:ENTRY + 0x17c]
    assert trial[TOS + 0xd0:TOS + 0xf0] == hashlib.sha256(
        trial[ENTRY:TOS + TOS_LEN - 256]).digest()
    allowed = ((KEY, KEY + 256), (TOS + 0xd0, TOS + 0xf0),
               (ENTRY, ENTRY + 4), (CAVE, CAVE + 80),
               (TOS + TOS_LEN - 256, TOS + TOS_LEN),
               (DRIVER + DRIVER_LEN - 256, DRIVER + DRIVER_LEN))
    assert all(any(start <= i < end for start, end in allowed)
               for i, (old, new) in enumerate(zip(clean, trial)) if old != new)
    modulus = int.from_bytes(trial[KEY:KEY + 256], 'little')
    public = rsa.RSAPublicNumbers(65537, modulus).public_key()
    pss = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)
    for start, length in ((TOS, TOS_LEN), (DRIVER, DRIVER_LEN)):
        public.verify(trial[start + length - 256:start + length],
                      trial[start:start + length - 256], pss, hashes.SHA256())
    assert int.from_bytes(trial[CAVE + 0x30:CAVE + 0x34], 'little') == 0xe3530000 | expected


def run_case(trial, expected, measured, status):
    arm = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    arm.mem_map(0, 0x20000)
    arm.mem_write(0, trial[ENTRY:ENTRY + 0x14000])
    arm.reg_write(UC_ARM_REG_R0, 1)
    arm.reg_write(UC_ARM_REG_LR, 0x12345678)
    visits, calls = [], []

    def stop_at_decision(machine, address, size, unused):
        if address in (0, 0x5c00, 0x5c44, 0x98, 0x190):
            visits.append(address)
        if address in (0x5c44, 0x190):
            machine.emu_stop()

    def service(machine, interrupt, unused):
        calls.append((interrupt, machine.reg_read(UC_ARM_REG_R0),
                      machine.reg_read(UC_ARM_REG_R1),
                      machine.reg_read(UC_ARM_REG_R2)))
        machine.mem_write(machine.reg_read(UC_ARM_REG_R1), measured.to_bytes(4, 'little'))
        machine.reg_write(UC_ARM_REG_R0, status)

    arm.hook_add(uc.UC_HOOK_CODE, stop_at_decision)
    arm.hook_add(uc.UC_HOOK_INTR, service)
    arm.emu_start(0, 0x200, timeout=1000000, count=2000)
    assert calls == [(2, 0x1f81c, 0x5c48, 4)]
    passes = status == 0 and measured == expected
    assert visits == ([0, 0x5c00, 0x98, 0x190] if passes else
                      [0, 0x5c00, 0x5c44])
    if passes:
        assert arm.reg_read(UC_ARM_REG_R0) == 1
        assert arm.reg_read(UC_ARM_REG_LR) == 0x12345678


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', required=True, type=Path)
    parser.add_argument('--expect-zero', required=True, type=Path)
    parser.add_argument('--expect-three', required=True, type=Path)
    args = parser.parse_args()
    clean = args.clean.read_bytes()
    for expected, path in ((0, args.expect_zero), (3, args.expect_three)):
        trial = path.read_bytes()
        verify_signed_view(clean, trial, expected)
        for measured in (0, 3):
            for status in (0, 1):
                run_case(trial, expected, measured, status)
    print('PASS: 8 native harvest-guard cases, signatures and exact ROM differences')


if __name__ == '__main__':
    main()
