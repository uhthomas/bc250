#!/usr/bin/env python3
"""Verify a RAM-only TOS first-instruction detour against its native reset path."""
import argparse
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import unicorn as uc
from unicorn.arm_const import (UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0,
                               UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                               UC_ARM_REG_SP)

TOS, TOS_LEN = 0x8eac00, 0x14350
DRIVER, DRIVER_LEN = 0x984f00, 0x1a770
KEY = 0x9db140
ENTRY = TOS + 0x100
CAVE = ENTRY + 0x5c00
REGISTERS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
             UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)


def run_reset(image, initial_r0):
    arm = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    arm.mem_map(0, 0x20000)
    arm.mem_write(0, image[ENTRY:ENTRY + 0x14000])
    arm.reg_write(UC_ARM_REG_R0, initial_r0)
    arm.reg_write(UC_ARM_REG_LR, 0x12345678)
    visits = []

    def stop_at_stack_setup(machine, address, size, unused):
        if address in (0, 0x5c00, 0x98, 0x140, 0x178, 0x190):
            visits.append(address)
        if address == 0x190:
            machine.emu_stop()

    arm.hook_add(uc.UC_HOOK_CODE, stop_at_stack_setup)
    arm.emu_start(0, 0x200, timeout=1000000, count=2000)
    return visits, tuple(arm.reg_read(register) for register in REGISTERS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean', required=True, type=Path)
    parser.add_argument('--trial', required=True, type=Path)
    args = parser.parse_args()
    clean, trial = args.clean.read_bytes(), args.trial.read_bytes()
    assert len(clean) == len(trial) == 0x1000000
    assert clean[ENTRY:ENTRY + 4] == bytes.fromhex('240000ea')
    assert trial[ENTRY:ENTRY + 4] == bytes.fromhex('fe1600ea')
    assert trial[CAVE:CAVE + 4] == bytes.fromhex('24e9ffea')
    assert trial[ENTRY + 0x178:ENTRY + 0x17c] == clean[ENTRY + 0x178:ENTRY + 0x17c]
    assert trial[TOS + 0xd0:TOS + 0xf0] == hashlib.sha256(
        trial[ENTRY:TOS + TOS_LEN - 256]).digest()
    allowed = ((KEY, KEY + 256), (TOS + 0xd0, TOS + 0xf0),
               (ENTRY, ENTRY + 4), (CAVE, CAVE + 4),
               (TOS + TOS_LEN - 256, TOS + TOS_LEN),
               (DRIVER + DRIVER_LEN - 256, DRIVER + DRIVER_LEN))
    assert all(any(start <= i < end for start, end in allowed)
               for i, (old, new) in enumerate(zip(clean, trial)) if old != new)
    modulus = int.from_bytes(trial[KEY:KEY + 256], 'little')
    public = rsa.RSAPublicNumbers(65537, modulus).public_key()
    pss = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)
    for start, length in ((TOS, TOS_LEN), (DRIVER, DRIVER_LEN)):
        body = trial[start:start + length - 256]
        signature = trial[start + length - 256:start + length]
        public.verify(signature, body, pss, hashes.SHA256())
    for initial_r0 in (0, 1):
        original_visits, original_state = run_reset(clean, initial_r0)
        trial_visits, trial_state = run_reset(trial, initial_r0)
        assert original_visits == [0, 0x98, 0x140, 0x178, 0x190]
        assert trial_visits == [0, 0x5c00, 0x98, 0x140, 0x178, 0x190]
        assert trial_state == original_state
    print('PASS: signed TOS entry detour rejoins stock reset with identical registers')


if __name__ == '__main__':
    main()
