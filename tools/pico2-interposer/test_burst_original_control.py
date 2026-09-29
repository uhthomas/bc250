#!/usr/bin/env python3
"""Pin exact-original pilot reply bytes and both recorded command adjacencies."""

import hashlib
import json
from pathlib import Path
import re
import unittest

from analyze_full_cs_stream import expand
from test_burst_select_od_model import replay, synthetic_samples
from fast_select_model import assemble


ROOT = Path(__file__).resolve().parents[2]
HEADER = Path(__file__).with_name('burst_original_reply.h')
ROM = ROOT / 'output/waveshare-recovery-20260925/waveshare-restore-20260925T1448Z/control.rom'
TRACE = ROOT / 'output/pico2/boot-rle-20260927.bin'
TRACE_META = TRACE.with_suffix('.json')
PIOASM = ROOT / 'output/pico2/build-uefi-burst-riscv/pioasm/pioasm'


class OriginalBurstControl(unittest.TestCase):
    def test_reply_is_exact_working_rom(self):
        rom = ROM.read_bytes()
        self.assertEqual(hashlib.sha256(rom).hexdigest(),
                         'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183')
        source = HEADER.read_text()
        words = [int(x, 16) for x in re.findall(r'0x([0-9a-f]{8})u',
                                                   source.split('burst_original_words')[1])]
        self.assertEqual(len(words), 16)
        data = b''.join(word.to_bytes(4, 'big') for word in words)
        self.assertEqual(data, rom[0xae0140:0xae0180])

    def test_target_follows_trigger_in_both_recorded_boot_passes(self):
        if not TRACE.is_file():
            self.skipTest('private full-command capture absent')
        commands = expand(TRACE.read_bytes(), json.loads(TRACE_META.read_text()))
        pairs = [(i, commands[i:i+3]) for i in range(len(commands)-2)
                 if commands[i] == 0x03ae0100]
        self.assertEqual(len(pairs), 2)
        self.assertTrue(all(rows == [0x03ae0100, 0x03ae00c0, 0x03ae0140]
                            for _, rows in pairs))

    def test_target_reply_passes_two_cycle_selector_model(self):
        if not PIOASM.is_file():
            self.skipTest('PIO assembler absent')
        rom = ROM.read_bytes()
        cmd = 0x03ae0140
        reply = rom[0xae0140:0xae0180]
        program = assemble(str(PIOASM), 'burst_select_od.pio')
        rises, state, irqs, remaining = replay(program,
                                               synthetic_samples(cmd, reply),
                                               cmd, reply, sync_cycles=2)
        self.assertEqual(len(rises), 544)
        self.assertEqual(irqs, set())
        self.assertEqual(remaining, [])
        self.assertTrue(all(flash_cs == 1 and oe == 1
                            for flash_cs, oe, _ in rises[32:]))
        expected = [(byte >> bit) & 1 for byte in reply for bit in range(7, -1, -1)]
        self.assertEqual([data for _, _, data in rises[32:]], expected)
        self.assertEqual(state['oe'], 0)


if __name__ == '__main__':
    unittest.main()
