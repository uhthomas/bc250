#!/usr/bin/env python3
"""Replay the two-pass address schedule against complete original boot traces."""

import json
from pathlib import Path
import unittest

from analyze_full_cs_stream import expand
from prepare_same_length_payload import ROM_START, ROM_END, BLOCK


ROOT = Path(__file__).resolve().parents[2]
TRACES = (
    ROOT / 'output/pico2/boot-rle-20260927.bin',
    ROOT / 'output/video-decode-20260922/df-lock-control-20260928/boot-20260928.bin',
)


def match_schedule(commands: list[int]) -> list[tuple[int, int]]:
    count = (ROM_END - ROM_START) // BLOCK
    index = 0
    matched = []
    for transaction, command in enumerate(commands):
        if index == 2 * count:
            break
        expected = 0x03000000 | (ROM_START + index % count * BLOCK)
        if command == expected:
            matched.append((transaction, command))
            index += 1
    if index != 2 * count:
        raise ValueError(f'incomplete two-pass sequence: {index}/{2 * count}')
    for (transaction_a, _), (transaction_b, _) in zip(matched, matched[1:]):
        if transaction_b != transaction_a + 1 and transaction_b != matched[count][0]:
            raise ValueError('nonconsecutive changed-region read within a pass')
    return matched


class DfLockStreamSchedule(unittest.TestCase):
    def test_both_complete_captures_have_two_contiguous_changed_regions(self):
        if not all(path.is_file() for path in TRACES):
            self.skipTest('private full-command boot traces absent')
        count = (ROM_END - ROM_START) // BLOCK
        self.assertEqual(count, 20727)
        for path in TRACES:
            with self.subTest(path=path):
                commands = expand(path.read_bytes(), json.loads(path.with_suffix('.json').read_text()))
                matched = match_schedule(commands)
                self.assertEqual(len(matched), 2 * count)
                self.assertEqual(matched[0][1], 0x03AEDE80)
                self.assertEqual(matched[count - 1][1], 0x03C31C00)
                self.assertEqual(matched[count][1], 0x03AEDE80)
                self.assertEqual(matched[-1][1], 0x03C31C00)
                self.assertGreater(matched[count][0] - matched[count - 1][0], 1000)
                self.assertEqual(sum(word == 0x03AEDE80 for word in commands), 2)

    def test_missing_one_burst_is_detected(self):
        stream = [0x03000000 | (ROM_START + i * BLOCK)
                  for i in range((ROM_END - ROM_START) // BLOCK)] * 2
        stream.pop(100)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            match_schedule(stream)


if __name__ == '__main__':
    unittest.main()
