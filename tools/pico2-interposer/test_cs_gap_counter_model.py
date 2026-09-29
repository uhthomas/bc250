#!/usr/bin/env python3
"""Digital check for the input-only CS-high PIO counter."""

import collections
import unittest

from fast_select_model import assemble
from router_model import SM
from test_burst_select_od_model import PIOASM


class GapCounter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PIOASM.is_file():
            raise unittest.SkipTest('PIO assembler not present in local build')
        cls.program = assemble(str(PIOASM), 'cs_gap_counter.pio')

    def test_counts_high_interval_and_never_writes_pins(self):
        instructions = [int(x['hex'], 16) for x in self.program['instructions']]
        self.assertLessEqual(len(instructions), 8)
        self.assertFalse(any(i >> 13 in (3, 7) for i in instructions))
        sm = SM(self.program, jmp_pin=2)
        pipe = collections.deque([0] * 2)
        irqs = set()
        for state, cycles in ((0, 30), (1, 120), (0, 40),
                              (1, 240), (0, 40)):
            for _ in range(cycles):
                pipe.append(state << 2)
                sm.step(pipe.popleft(), irqs)
        self.assertEqual(len(sm.rx), 2)
        counts = [0xffffffff - word for word in sm.rx]
        self.assertGreater(counts[0], 54)
        self.assertLess(counts[0], 62)
        self.assertGreater(counts[1], 114)
        self.assertLess(counts[1], 122)


if __name__ == '__main__':
    unittest.main()
