#!/usr/bin/env python3
"""Check that the unwired XIP probe preserves the proven selector timing."""

import collections
import unittest

from fast_select_model import assemble
from router_model import SM
from test_burst_select_od_model import PIOASM, synthetic_samples


class XipBenchPio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PIOASM.is_file():
            raise unittest.SkipTest('PIO assembler not present in local build')
        cls.live = assemble(str(PIOASM), 'burst_match_late_od.pio')
        cls.bench = assemble(str(PIOASM), 'burst_xip_bench.pio')
        cls.capture = assemble(str(PIOASM), 'burst_xip_capture.pio')

    def test_selector_has_only_gpio_number_changes(self):
        a = [int(x['hex'], 16) for x in self.live['instructions']]
        b = [int(x['hex'], 16) for x in self.bench['instructions']]
        self.assertEqual((len(a), len(b)), (32, 32))
        self.assertEqual((self.live['wrap'], self.live['wrapTarget']),
                         (self.bench['wrap'], self.bench['wrapTarget']))
        for index, (original, test) in enumerate(zip(a, b)):
            with self.subTest(index=index):
                if original >> 13 == 1:  # WAIT GPIO: only the pin number moves.
                    self.assertEqual(original & ~31, test & ~31)
                    self.assertEqual(test & 31,
                                     {2: 9, 3: 10}[original & 31])
                else:
                    self.assertEqual(original, test)

    def test_input_only_capture_collects_exactly_64_bytes(self):
        self.assertLessEqual(len(self.capture['instructions']), 32)
        reply = bytes((i * 73 + 19) & 255 for i in range(64))
        frame = synthetic_samples(0x03ae0140, reply)
        sm = SM(self.capture, in_base=8)
        pipe = collections.deque([1 << 9] * 2)
        irqs = set()
        for sample in [0x21] * 20 + frame:
            pins = ((sample & 1) << 9) | (((sample >> 1) & 1) << 10)
            pins |= (((sample >> 3) & 1) << 8)
            for _ in range(2):
                pipe.append(pins)
                sm.step(pipe.popleft(), irqs)
        self.assertEqual(irqs, {1})
        self.assertEqual(len(sm.rx), 16)
        self.assertEqual(sm.rx, [int.from_bytes(reply[i:i + 4], 'big')
                                 for i in range(0, 64, 4)])


if __name__ == '__main__':
    unittest.main()
