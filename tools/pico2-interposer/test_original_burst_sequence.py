#!/usr/bin/env python3
"""Exact-original control data must come only from the pinned whole-chip ROM."""
import hashlib
import re
import unittest
from pathlib import Path

from prepare_original_burst_sequence import (CONTROL_SHA256, COUNT, START,
                                             generate)


ROOT = Path(__file__).resolve().parents[2]
ROM = (ROOT / 'output/waveshare-recovery-20260925/'
       'waveshare-restore-20260925T1448Z/control.rom')


class OriginalBurstSequence(unittest.TestCase):
    def test_pinned_rom_and_all_words(self):
        if not ROM.is_file():
            self.skipTest('private working-ROM backup absent')
        rom = ROM.read_bytes()
        self.assertEqual(hashlib.sha256(rom).hexdigest(), CONTROL_SHA256)
        result = generate(rom)
        words = [int(x, 16) for x in re.findall(r'0x([0-9a-f]{8})u', result)]
        self.assertEqual(words[0], START)
        actual = words[1:]
        expected = [int.from_bytes(rom[START + i:START + i + 4], 'big')
                    for i in range(0, COUNT * 64, 4)]
        self.assertEqual(actual, expected)
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            modified = bytearray(rom)
            modified[START + 3] ^= 1
            generate(modified)


if __name__ == '__main__':
    unittest.main()
