#!/usr/bin/env python3
"""Execute the pinned VCN post-load function offline with explicit I/O stubs.

Authentication is outside this experiment. It models neither the PSP fabric nor
VCN silicon; it traces what the real post-load instructions request and check.
"""
import hashlib
import json
from pathlib import Path
import struct

import unicorn as uc
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

ROOT = Path(__file__).resolve().parents[2] / 'output/video-decode-20260922/psp-analysis'
rom = (ROOT.parents[1] / 'firmware-prep/meimei-dxev3/BC250_3.00_MeiMeiDXEv3.ROM').read_bytes()
assert hashlib.sha256(rom).hexdigest() == '3d9828415dfdd41eb6c83d770ca04d2e552e371ec277123f05a6d689c9a24736'
driver = (ROOT / 'DRIVER_ENTRIES.bin').read_bytes()
assert driver == rom[0x984f00:0x984f00+len(driver)]
assert uc.__version__ == '2.1.4'
STACK, MAPPING, STOP = 0x20000000, 0x30000000, 0x50000000
REGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
word = lambda x: struct.pack('<I', x)


def run_case(context, smn_result, mapping_result, existing_aux_flag,
             driver_override=None, expected_result=None, expected_smn_addresses=None,
             readback=None, readback_address=0x0900c004, extra_write=None,
             readbacks=None, loaded_before=0):
    m = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB)
    m.mem_map(0xe00000, 0x18000, uc.UC_PROT_READ | uc.UC_PROT_EXEC)
    m.mem_map(0xe18000, 0x98000, uc.UC_PROT_READ | uc.UC_PROT_WRITE)
    m.mem_write(0xe00000, driver if driver_override is None else driver_override)
    m.mem_map(STACK, 0x10000)
    m.mem_map(MAPPING, 0x1000)
    m.mem_map(STOP, 0x1000, uc.UC_PROT_READ | uc.UC_PROT_EXEC)
    m.mem_write(MAPPING, b'\xa5' * 0x1000)
    # Synthetic allocated TMR state, explicitly not a capture of hardware RAM.
    m.mem_write(0xe35cc0, word(0x62ec0) + word(0x100000))
    m.mem_write(0xe18b88, struct.pack('<Q', 0xf400000000))
    m.mem_write(0xe55178 + 0x13, bytes([existing_aux_flag]))
    m.mem_write(0xe55178 + 13, bytes([loaded_before]))
    for r, v in ((UC_ARM_REG_R0, 13), (UC_ARM_REG_R1, context), (UC_ARM_REG_R2, 0x62ec0),
                 (UC_ARM_REG_SP, STACK+0x8000), (UC_ARM_REG_LR, STOP|1)):
        m.reg_write(r, v)
    events, writes = [], []
    returned = False

    def code(mu, address, size, user):
        nonlocal returned
        if address == STOP:
            returned = True
            mu.emu_stop()
        elif address == 0xe06900:
            hi, lo, length, slot_pointer = [mu.reg_read(r) for r in REGS]
            sp = mu.reg_read(UC_ARM_REG_SP)
            destination_pointer = struct.unpack('<I', mu.mem_read(sp, 4))[0]
            assert length == 0x1000 and (hi << 32 | lo) == 0xf400162ec0
            assert STACK <= slot_pointer < STACK+0x10000
            assert STACK <= destination_pointer < STACK+0x10000-4
            events.append({'stub': 'map_buffer', 'address': hex(hi << 32 | lo),
                           'bytes': length, 'result': hex(mapping_result)})
            if mapping_result == 0:
                mu.mem_write(slot_pointer, b'\x01')
                mu.mem_write(destination_pointer, word(MAPPING))
            mu.reg_write(UC_ARM_REG_R0, mapping_result)
            mu.reg_write(UC_ARM_REG_PC, mu.reg_read(UC_ARM_REG_LR))

    def interrupt(mu, number, user):
        assert number == 2
        pc = mu.reg_read(UC_ARM_REG_PC)
        instruction = bytes(mu.mem_read(pc-2, 2))
        assert instruction[1] == 0xdf
        svc = instruction[0]
        if svc == 0x7c:
            address, value, size, _ = [mu.reg_read(r) for r in REGS]
            assert ((address in (0x0900c004, 0x1f8a4) and value == 1) or
                    (extra_write is not None and (address, value) == extra_write)) and size == 4
            service_result = smn_result[address] if isinstance(smn_result, dict) else smn_result
            events.append({'stub_svc': '0x7c', 'address': hex(address), 'value': value,
                           'bytes': size, 'result': hex(service_result)})
            mu.reg_write(UC_ARM_REG_R0, service_result)
        elif svc == 0x7b:
            address, output, size, _ = [mu.reg_read(r) for r in REGS]
            assert size == 4
            assert STACK <= output < STACK + 0x10000 - 4
            if readbacks is None:
                assert readback is not None and address == readback_address
                service_result, value = readback
            else:
                assert address in readbacks
                service_result, value = readbacks[address]
            if service_result == 0:
                mu.mem_write(output, word(value))
            events.append({'stub_svc': '0x7b', 'address': hex(address),
                           'bytes': size, 'result': hex(service_result),
                           'value': hex(value) if service_result == 0 else None})
            mu.reg_write(UC_ARM_REG_R0, service_result)
        elif svc == 0x6c:
            assert mu.reg_read(UC_ARM_REG_R0) == 1
            events.append({'stub_svc': '0x6c', 'slot': 1})
            mu.reg_write(UC_ARM_REG_R0, 0)
        else:
            raise AssertionError(f'Unexpected SVC {svc:#x}')

    def store(mu, access, address, size, value, user):
        if STACK <= address < STACK+0x10000:
            return
        assert (address in (MAPPING, MAPPING+0x40) and size == 4 and value == 0) or (
            address == 0xe55178+13 and size == 1 and value == 1), f'Unexpected store {address:#x}'
        writes.append({'address': hex(address), 'bytes': size, 'value': value})

    m.hook_add(uc.UC_HOOK_CODE, code)
    m.hook_add(uc.UC_HOOK_INTR, interrupt)
    m.hook_add(uc.UC_HOOK_MEM_WRITE, store)
    m.emu_start(0xe0fb19, STOP+2, timeout=1000000, count=10000)
    assert returned
    result = m.reg_read(UC_ARM_REG_R0)
    expected = 0 if existing_aux_flag else mapping_result
    assert result == (expected if expected_result is None else expected_result)
    addresses = (expected_smn_addresses if expected_smn_addresses is not None else
                 (['0x900c004', '0x1f8a4'] if context == 0xffff else ['0x1f8a4']))
    assert [x['address'] for x in events if x.get('stub_svc') == '0x7c'] == addresses
    return {'context': hex(context), 'smn_stub_result': (
                {hex(key): hex(value) for key, value in smn_result.items()}
                if isinstance(smn_result, dict) else hex(smn_result)),
            'mapping_stub_result': hex(mapping_result), 'aux_flag_0x13': existing_aux_flag,
            'return': hex(result), 'loaded_flag': int(m.mem_read(0xe55178+13, 1)[0]),
            'events': events, 'writes': writes}


if __name__ == '__main__':
    cases = [run_case(context, smn, mapping, flag)
             for context in (0xffff, 0) for smn in (0, 0xffff0001)
             for mapping in (0, 0xffff0007) for flag in (0, 1)]
    for c in cases:
        print(f"context={c['context']} smn={c['smn_stub_result']} mapping={c['mapping_stub_result']} aux={c['aux_flag_0x13']} -> {c['return']}")
    (ROOT / 'vcn-postload-emulation.json').write_text(json.dumps({
        'function': '0xe0fb18', 'cases': cases,
        'limits': 'Synthetic TMR state and SVC/map stubs; no authentication, fabric, or VCN silicon model.'
    }, indent=2) + '\n')
