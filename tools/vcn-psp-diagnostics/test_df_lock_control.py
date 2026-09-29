#!/usr/bin/env python3
"""Execute the original and omitted DF-lock call path in pinned x86 code.

Only the local call/return boundary is modeled. This cannot prove that the
module runs on the board or that omitting the BIOS command unlocks any SMN bit.
"""

import hashlib
import json
from pathlib import Path
import struct
import sys

import unicorn as uc
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EDX,
    UC_X86_REG_RAX, UC_X86_REG_RBP, UC_X86_REG_RCX, UC_X86_REG_RIP,
    UC_X86_REG_RDI, UC_X86_REG_RSP,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_df_lock_control import CALL_OFFSET, PE_SHA256, REPLACEMENT, prepare
from prepare_df_lock_bootdone_control import EXIT_CALL_OFFSET, prepare as prepare_both


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'output/video-decode-20260922/uefi-analysis/iohc-image-manifest.json'
STACK = 0x100000
BUFFER = 0x400000
STOP = 0x22bf


def run_case(code: bytes, helper_result: int, start=0x2291, stop=STOP):
    m = uc.Uc(uc.UC_ARCH_X86, uc.UC_MODE_64)
    m.mem_map(0, 0x4000)
    m.mem_write(0, code)
    m.mem_map(STACK, 0x10000)
    m.mem_map(BUFFER, 0x1000)
    m.reg_write(UC_X86_REG_RSP, STACK + 0x8000)
    m.reg_write(UC_X86_REG_RDI, BUFFER)
    m.reg_write(UC_X86_REG_RBP, 0x80000000)
    calls = []
    stopped = False

    def on_code(machine, pc, size, _):
        nonlocal stopped
        if pc == stop:
            stopped = True
            machine.emu_stop()
        elif pc in (0x1f28, 0xf80):
            if pc == 0x1f28:
                calls.append((pc, machine.reg_read(UC_X86_REG_EDX),
                              machine.reg_read(UC_X86_REG_RCX),
                              struct.unpack('<I', machine.mem_read(BUFFER, 4))[0]))
            stack = machine.reg_read(UC_X86_REG_RSP)
            ret, = struct.unpack('<Q', machine.mem_read(stack, 8))
            machine.reg_write(UC_X86_REG_RSP, stack + 8)
            machine.reg_write(UC_X86_REG_RAX, helper_result if pc == 0x1f28 else 0)
            machine.reg_write(UC_X86_REG_RIP, ret)

    m.hook_add(uc.UC_HOOK_CODE, on_code)
    m.emu_start(start, stop + 2, timeout=1_000_000, count=1000)
    assert stopped
    return dict(calls=calls, ebx=m.reg_read(UC_X86_REG_EBX),
                buffer=struct.unpack('<I', m.mem_read(BUFFER, 4))[0],
                edx=m.reg_read(UC_X86_REG_EDX), eax=m.reg_read(UC_X86_REG_EAX))


def main():
    manifest = json.loads(MANIFEST.read_text())
    item, = (x for x in manifest['images'] if x['name'] == 'AmdPspDxeV2')
    original = (ROOT / 'output/video-decode-20260922' / item['path']).read_bytes()
    assert hashlib.sha256(original).hexdigest() == PE_SHA256 == item['sha256']
    assert original[0x6d3:0x6d8] == bytes.fromhex('e86c1b0000')
    assert original[CALL_OFFSET:CALL_OFFSET+5] != REPLACEMENT
    changed = prepare(original)
    assert changed[CALL_OFFSET:CALL_OFFSET+5] == REPLACEMENT
    assert len(original) == len(changed)
    success = run_case(original, 1)
    failure = run_case(original, 0)
    omission = run_case(changed, 1)
    assert success['calls'] == failure['calls'] == [(0x1f28, 0x1b, BUFFER, 0x10)]
    assert omission['calls'] == []
    assert (success['ebx'], failure['ebx'], omission['ebx']) == (1, 0, 1)
    assert success['buffer'] == failure['buffer'] == omission['buffer'] == 0x10
    both = prepare_both(original)
    exit_original = run_case(original, 1, 0x8b9, 0x8c6)
    exit_single = run_case(changed, 1, 0x8b9, 0x8c6)
    exit_both = run_case(both, 1, 0x8b9, 0x8c6)
    assert exit_original['calls'] == exit_single['calls'] == [(0x1f28, 0x6, BUFFER, 0)]
    assert exit_both['calls'] == []
    assert (exit_original['ebx'], exit_single['ebx'], exit_both['ebx']) == (0, 0, 0)
    assert (exit_original['eax'], exit_single['eax'], exit_both['eax']) == (1, 1, 1)
    assert both[EXIT_CALL_OFFSET:EXIT_CALL_OFFSET+5] == REPLACEMENT
    print('PASS: pinned callback -> DF-lock caller, original/omitted 0x1b and 0x06 mailbox requests')
    print(f'control PE SHA256 {hashlib.sha256(changed).hexdigest()}')
    print(f'two-command PE SHA256 {hashlib.sha256(both).hexdigest()}')


if __name__ == '__main__':
    main()
