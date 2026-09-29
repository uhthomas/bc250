#!/usr/bin/env python3
"""Cycle replay of three four-byte replies at the board's shortest CS gap."""

import collections
import hashlib
from pathlib import Path
import re
import unittest

from fast_select_model import assemble
from router_model import SM
from test_burst_select_od_model import PIOASM, ROM_PATH


TARGETS = (0x03AE0088, 0x03AE008C, 0x03AE0090)
MIN_GAP_CYCLES = 60  # Measured 176 ns, rounded to 340 MHz PIO cycles.


def frame(command: int, reply: bytes, gap_cycles: int):
    assert len(reply) == 4 and gap_cycles % 2 == 0
    data = command.to_bytes(4, 'big') + reply
    samples = []
    for bit in range(64):
        value = (data[bit // 8] >> (7 - bit % 8)) & 1
        pins = (value << 2) if bit < 32 else (value << 3)
        samples.extend([pins] * 2 + [pins | 2] * 3)
    return samples + [0x21] * (gap_cycles // 2)


def replay(program, rom: bytes, commands, gap_cycles=MIN_GAP_CYCLES):
    fifo = collections.deque()
    for command in TARGETS:
        fifo.append(command >> 1)
        fifo.append(int.from_bytes(rom[command & 0xFFFFFF:(command & 0xFFFFFF) + 4], 'big'))
    fifo.append(0xFFFFFFFF)  # PASS sentinel after the third active read.
    sm = SM(program, fifo, jmp_pin=4, out_autopull=True, out_threshold=32)
    pipe = collections.deque([4] * 2)
    irqs = set()
    state = dict(flash_cs=1, oe=0, data=0)
    rises = [[] for _ in commands]
    previous_cs, previous_clk = 1, 0
    transaction = -1
    for sample in [0x21] * 40 + [value for command in commands
                                  for value in frame(command,
                                      rom[command & 0xFFFFFF:(command & 0xFFFFFF) + 4],
                                      gap_cycles)]:
        cs, clk = sample & 1, (sample >> 1) & 1
        if previous_cs and not cs:
            transaction += 1
        if not cs and clk and not previous_clk:
            rises[transaction].append((state['flash_cs'], state['oe'], state['data']))
        previous_cs, previous_clk = cs, clk
        for _ in range(2):
            pipe.append((sample & 7) << 2)
            state.update(sm.step(pipe.popleft(), irqs))
    return rises, state, irqs, list(fifo), sm


class ShortScanSequence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PIOASM.is_file() or not ROM_PATH.is_file():
            raise unittest.SkipTest('local PIO assembler or private working ROM absent')
        cls.program = assemble(str(PIOASM), 'short_scan_sequence_od.pio')
        cls.rom = ROM_PATH.read_bytes()
        assert hashlib.sha256(cls.rom).hexdigest() == (
            'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183')

    def test_three_targets_and_following_pass_at_measured_minimum_gap(self):
        commands = [0x03AE0000 + 4 * i for i in range(39)]
        rises, state, irqs, fifo, sm = replay(self.program, self.rom, commands)
        self.assertEqual(len(self.program['instructions']), 32)
        self.assertEqual(irqs, {1})
        self.assertEqual(fifo, [])
        self.assertEqual([len(row) for row in rises], [64] * len(commands))
        for command, row in zip(commands, rises):
            if command not in TARGETS:
                self.assertTrue(all(cs == 0 and oe == 0 for cs, oe, _ in row),
                                f'{command:08x}: pass route failed')
                continue
            self.assertTrue(all(cs == 0 and oe == 0 for cs, oe, _ in row[:31]))
            self.assertEqual(row[31][:2], (1, 0))
            self.assertTrue(all(cs == 1 and oe == 1 for cs, oe, _ in row[32:]))
            data = self.rom[command & 0xFFFFFF:(command & 0xFFFFFF) + 4]
            expected = [(byte >> bit) & 1 for byte in data for bit in range(7, -1, -1)]
            self.assertEqual([bit for _, _, bit in row[32:]], expected)
        self.assertEqual(state['flash_cs'], 1)
        self.assertEqual(state['oe'], 0)
        self.assertEqual(sm.x, 0xFFFFFFFF)

    def test_odd_address_fails_before_driving_miso(self):
        odd = TARGETS[0] | 1
        rises, _, irqs, _, _ = replay(self.program, self.rom, [odd])
        self.assertIn(0, irqs)
        self.assertTrue(all(oe == 0 for _, oe, _ in rises[0]))

    def test_board_control_words_are_exact_original_bytes(self):
        source = Path(__file__).with_name('short_scan_original_control.c').read_text()
        match = re.search(r'static const uint32_t replies\[3\] = \{([^}]+)\};', source)
        self.assertIsNotNone(match)
        words = [int(value, 16) for value in re.findall(r'0x([0-9a-f]{8})u', match.group(1))]
        expected = [int.from_bytes(self.rom[c & 0xFFFFFF:(c & 0xFFFFFF) + 4], 'big')
                    for c in TARGETS]
        self.assertEqual(words, expected)


if __name__ == '__main__':
    unittest.main()
