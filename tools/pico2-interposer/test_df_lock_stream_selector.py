#!/usr/bin/env python3
"""Replay boundary and middle candidate bursts through the proven selector."""

import hashlib
from pathlib import Path
import unittest

from fast_select_model import assemble
from test_burst_match_late_model import replay
from test_burst_select_od_model import PIOASM, synthetic_samples
from prepare_same_length_payload import ROM_START, ROM_END, BLOCK, CANDIDATE_SHA256


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / 'output/video-decode-20260922/df-lock-control-20260928/UNTESTED-NEVER-flash-df-lock-same-length.rom'


class DfLockStreamSelector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PIOASM.is_file() or not CANDIDATE.is_file():
            raise unittest.SkipTest('PIO assembler or private equal-length candidate absent')
        cls.program = assemble(str(PIOASM), 'burst_match_late_od.pio')
        cls.image = CANDIDATE.read_bytes()
        assert hashlib.sha256(cls.image).hexdigest() == CANDIDATE_SHA256

    def test_first_middle_and_last_candidate_reply(self):
        for address in (ROM_START, ROM_START + (ROM_END - ROM_START) // (2 * BLOCK) * BLOCK,
                        ROM_END - BLOCK):
            with self.subTest(address=hex(address)):
                command = 0x03000000 | address
                reply = self.image[address:address + BLOCK]
                rows, state, irqs, fifo, sm, release, drive, data_rise = replay(
                    self.program, [synthetic_samples(command, reply)], command, reply)
                self.assertEqual(len(rows[0]), 544)
                self.assertEqual(irqs, {1})
                self.assertEqual(fifo, [])
                self.assertEqual(sm.dma_left, 0)
                self.assertGreaterEqual(drive - release, 4)
                self.assertGreaterEqual(data_rise - drive, 2)
                expected = [(byte >> bit) & 1 for byte in reply for bit in range(7, -1, -1)]
                self.assertEqual([bit for _, _, bit in rows[0][32:]], expected)
                self.assertEqual(state['oe'], 0)


if __name__ == '__main__':
    unittest.main()
