#!/usr/bin/env python3
"""Execute the RAM-only BC250 video TMR patch with modeled register services.

The pinned driver instructions and region allocator execute. SVC register I/O
and address protection are software fixtures, not a hardware result.
"""
import argparse
import importlib.util
from pathlib import Path
import re
import struct

import unicorn as uc
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_SP


def load_module(path):
    spec = importlib.util.spec_from_file_location('bc250_tmr', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(tmr, rom, fill, region_bytes, occupied, fail_video_control=False,
        expect_guard_error=False, expect_rsmu=False, gasket_rows=(),
        fail_gasket_at=None, skip_native_video_control=False):
    s = tmr.startup
    s.DRIVER = rom[0x984f00:0x99f670]
    m = tmr.initial_machine(fill)
    entry_sp = m.reg_read(UC_ARM_REG_SP)
    stopped = False

    def startup_stop(mu, pc, size, _):
        nonlocal stopped
        if pc == 0xe09626:
            stopped = True
            mu.emu_stop()

    def no_interrupt(mu, number, _):
        raise AssertionError(('startup interrupt', number, hex(mu.reg_read(UC_ARM_REG_PC))))

    h1 = m.hook_add(uc.UC_HOOK_CODE, startup_stop)
    h2 = m.hook_add(uc.UC_HOOK_INTR, no_interrupt)
    m.emu_start(0xe09623, 0xe09628, timeout=1000000, count=100000)
    assert stopped and m.reg_read(UC_ARM_REG_SP) == entry_sp
    m.hook_del(h1)
    m.hook_del(h2)
    metadata = s.STATE
    expected = bytearray(0x38)
    struct.pack_into('<III', expected, 0x10, 0x1f90c, 0x1f848, 0x1f844)
    assert bytes(m.mem_read(metadata, 0x38)) == expected

    class RegionModel(tmr.RegisterModel):
        def service(self, mu, svc):
            args = [mu.reg_read(r) for r in s.REGS]
            if svc == 0x7c and args[0] in gasket_addresses:
                assert args[2] == 4
                self.events.append({'svc': hex(svc),
                                    'arguments': [hex(x) for x in args]})
                index = len([event for event in self.events
                             if event['svc'] == '0x7c' and
                             int(event['arguments'][0], 16) in gasket_addresses]) - 1
                mu.reg_write(UC_ARM_REG_R0,
                             0xffff0001 if index == fail_gasket_at else 0)
                return
            if svc == 0x7c and args[0] in (0x0900c814, 0x0900c818,
                                           0x0900c824, 0x0900c810):
                assert args[2] == 4
                self.events.append({'svc': hex(svc),
                                    'arguments': [hex(x) for x in args]})
                mu.reg_write(UC_ARM_REG_R0, 0)
                return
            super().service(mu, svc)
            if (fail_video_control and svc == 0x7c and
                    self.events[-1]['arguments'][:2] == ['0x1f820', '0x185103']):
                mu.reg_write(UC_ARM_REG_R0, 0xffff0000)

    gasket_addresses = {address for address, _ in gasket_rows}
    model = RegionModel(occupied)
    args, descriptor = s.INPUT, s.INPUT+0x100
    m.mem_write(args, struct.pack('<II', descriptor, 0xffff))
    m.mem_write(descriptor, struct.pack('<III', tmr.TMR_BASE & 0xffffffff,
                                         tmr.TMR_BASE >> 32, region_bytes))
    m.reg_write(UC_ARM_REG_R0, args)
    m.reg_write(UC_ARM_REG_LR, s.STOP | 1)
    reached, allocations = False, []

    def code(mu, pc, size, _):
        nonlocal reached
        if pc == s.STOP:
            reached = True
            mu.emu_stop()
        elif pc == 0xe121ec:
            allocations.append(tuple(mu.reg_read(r) for r in s.REGS[:3]))

    def interrupt(mu, number, _):
        pc = mu.reg_read(UC_ARM_REG_PC)
        ins = bytes(mu.mem_read(pc-2, 2))
        assert number == 2 and ins[1] == 0xdf
        model.service(mu, ins[0])

    m.hook_add(uc.UC_HOOK_CODE, code)
    m.hook_add(uc.UC_HOOK_INTR, interrupt)
    m.emu_start(0xe0e7cd, s.STOP+2, timeout=1000000, count=200000)
    assert reached and m.reg_read(UC_ARM_REG_SP) == entry_sp
    result = m.reg_read(UC_ARM_REG_R0)
    if fail_gasket_at is not None:
        assert gasket_rows and not occupied and not fail_video_control
        assert result == 0xffff0001, hex(result)
    elif expect_guard_error:
        assert fail_video_control and not occupied
        assert result == 0xffff0000, hex(result)
        assert allocations == [(4, 0, 0x200000), (13, 0x200000, 0x100000)]
        assert struct.unpack('<I', m.mem_read(metadata+4, 4))[0] == 0
    elif occupied:
        assert result == 0xffff0008 and allocations == [(4, 0, 0x200000)]
        assert struct.unpack('<I', m.mem_read(metadata+4, 4))[0] == 0
    else:
        assert result == 0, hex(result)
        assert allocations == [(4, 0, 0x200000), (13, 0x200000, 0x100000)], allocations
        assert struct.unpack('<I', m.mem_read(metadata+4, 4))[0] == 0x200000
        assert model.regions[16] == tmr.TMR_BASE >> 16
        assert model.regions[20] == (tmr.TMR_BASE+0x200000-1) >> 16
        assert model.regions[24] == 0x805 and model.regions[28] == 0
        assert model.regions[32] == (tmr.TMR_BASE+0x200000) >> 16
        assert model.regions[36] == (tmr.TMR_BASE+0x300000-1) >> 16
        assert model.regions[40] == 0x37 and model.regions[44] == 0xc22
        assert (tmr.TMR_BASE+0x200000-1) < (tmr.TMR_BASE+0x200000)
        native_writes = [e for e in model.events if e['svc'] == '0x7c' and
                         e['arguments'][:2] == ['0x1f820', '0x185103']]
        assert len(native_writes) == (0 if skip_native_video_control else 1)
    assert bytes(m.mem_read(metadata+0x10, 12)) == expected[0x10:0x1c]
    rsmu_events = [(int(e['arguments'][0], 16), int(e['arguments'][1], 16))
                   for e in model.events if e['svc'] == '0x7c' and
                   int(e['arguments'][0], 16) in (0x0900c814, 0x0900c818,
                                                  0x0900c824, 0x0900c810)]
    if expect_rsmu and not (occupied or expect_guard_error):
        assert rsmu_events == [(0x0900c814, 0x03810100),
                               (0x0900c818, 0),
                               (0x0900c824, 0),
                               (0x0900c810, 0x8000)], rsmu_events
    else:
        assert not rsmu_events, rsmu_events
    gasket_events = [(int(e['arguments'][0], 16), int(e['arguments'][1], 16))
                     for e in model.events if e['svc'] == '0x7c' and
                     int(e['arguments'][0], 16) in gasket_addresses]
    expected_gasket = (list(gasket_rows[:fail_gasket_at+1]) if fail_gasket_at is not None
                       else list(gasket_rows) if not (occupied or expect_guard_error)
                       else [])
    assert gasket_events == expected_gasket, (gasket_events, expected_gasket)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tracer', required=True, type=Path)
    ap.add_argument('--rom', required=True, type=Path)
    ap.add_argument('--guard', action='store_true',
                    help='Expect the SVC-guard profile to propagate a rejected video-control write')
    ap.add_argument('--rsmu', action='store_true',
                    help='Expect the profile to run the signed client-12 RSMU helper after video allocation')
    ap.add_argument('--gasket-table', type=Path,
                    help='Expect the scoped client-12 policy writes after video allocation')
    ap.add_argument('--skip-native-video-control', action='store_true',
                    help='Assert the original 0x1f820 write is omitted and startup still returns')
    a = ap.parse_args()
    if a.skip_native_video_control and not a.guard:
        ap.error('--skip-native-video-control requires --guard')
    tmr = load_module(a.tracer)
    rom = a.rom.read_bytes()
    assert len(rom) == 0x1000000
    gasket_rows = [tuple(int(word, 16) for word in pair)
                   for pair in re.findall(r'\.word (0x[0-9a-f]+), (0x[0-9a-f]+)',
                                          a.gasket_table.read_text())] if a.gasket_table else []
    assert not a.gasket_table or len(gasket_rows) in (9, 14, 29, 31, 41, 46, 51)
    if gasket_rows:
        assert gasket_rows[0] == (0x0900c234, 0)
        assert gasket_rows[-1] == (0x0900c234, 1)
    results = [run(tmr, rom, fill, size, False, expect_rsmu=a.rsmu,
                   gasket_rows=gasket_rows,
                   skip_native_video_control=a.skip_native_video_control)
               for fill in (0xa5, 0x5a) for size in (0x400000, 0x800000)]
    results += [run(tmr, rom, fill, 0x400000, True, expect_rsmu=a.rsmu,
                    gasket_rows=gasket_rows,
                    skip_native_video_control=a.skip_native_video_control)
                for fill in (0xa5, 0x5a)]
    # The installed allocator ignores this particular video-control SVC
    # return value. Record the limitation instead of treating it as proof of
    # successful silicon control or guaranteed error propagation.
    results.append(run(tmr, rom, 0xa5, 0x400000, False,
                       fail_video_control=True,
                       expect_guard_error=a.guard and not a.skip_native_video_control,
                       expect_rsmu=a.rsmu, gasket_rows=gasket_rows,
                       skip_native_video_control=a.skip_native_video_control))
    assert results == [0]*4 + [0xffff0008]*2 + [
        0xffff0000 if a.guard and not a.skip_native_video_control else 0]
    if gasket_rows:
        assert run(tmr, rom, 0xa5, 0x400000, False, expect_rsmu=a.rsmu,
                   gasket_rows=gasket_rows, fail_gasket_at=8,
                   skip_native_video_control=a.skip_native_video_control) == 0xffff0001
    outcome = ('omitted' if a.skip_native_video_control else
               'propagated' if a.guard else 'ignored')
    print(f'PASS: {8 if gasket_rows else 7} scoped native video-TMR cases; '
          'regions do not overlap; '
          f'video-control SVC error is {outcome}; RSMU12 helper={a.rsmu}; '
          f'gasket12 rows={len(gasket_rows)}')


if __name__ == '__main__':
    main()
