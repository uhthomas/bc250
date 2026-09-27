#!/usr/bin/env python3
"""Execute the signed PSP driver trial's startup hook in a scoped native model."""
import argparse
import importlib.util
from pathlib import Path
import struct

import unicorn as uc
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP


def load_compare(path):
    spec = importlib.util.spec_from_file_location('compare_video', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--compare', type=Path, required=True)
    ap.add_argument('--clean', type=Path, required=True)
    ap.add_argument('--noop', type=Path, required=True)
    ap.add_argument('--metadata', type=Path, required=True)
    a = ap.parse_args()
    c = load_compare(a.compare)
    start, length = 0x984f00, 0x1a770
    blobs = {'clean': a.clean.read_bytes(), 'noop': a.noop.read_bytes(),
             'metadata': a.metadata.read_bytes()}
    results = []
    for fill in (0xa5, 0x5a):
        snapshots = {}
        for name, rom in blobs.items():
            c.FILES['bc250'] = rom[start:start+length]
            m = c.machine('bc250', fill)
            entry_sp = m.reg_read(UC_ARM_REG_SP)
            stopped = False

            def code(mu, pc, size, _):
                nonlocal stopped
                if pc == 0xe09626:
                    stopped = True
                    mu.emu_stop()

            def interrupt(mu, number, _):
                raise AssertionError(('unexpected SVC/interrupt', number,
                                      hex(mu.reg_read(UC_ARM_REG_PC))))

            m.hook_add(uc.UC_HOOK_CODE, code)
            m.hook_add(uc.UC_HOOK_INTR, interrupt)
            m.emu_start(0xe09623, 0xe09628, timeout=1000000, count=100000)
            assert stopped and m.reg_read(UC_ARM_REG_SP) == entry_sp, (name, fill)
            state = bytes(m.mem_read(c.bc.STATE, 0x38))
            expected = bytes([fill])*0x38
            if name == 'metadata':
                expected = bytearray(0x38)
                struct.pack_into('<III', expected, 0x10, 0x1f90c, 0x1f848, 0x1f844)
            assert state == expected, (name, fill, state.hex())
            snapshots[name] = bytes(m.mem_read(0xe1a000, c.BASE+c.SIZE-0xe1a000))
            results.append((name, fill, state.hex()))
        assert snapshots['clean'] == snapshots['noop']
        offset = c.bc.STATE - 0xe1a000
        assert (snapshots['clean'][:offset] + snapshots['clean'][offset+0x38:] ==
                snapshots['metadata'][:offset] + snapshots['metadata'][offset+0x38:])
    print('PASS: 6 scoped startup executions; no-op matches clean; metadata only changes 56-byte VCN state')


if __name__ == '__main__':
    main()
