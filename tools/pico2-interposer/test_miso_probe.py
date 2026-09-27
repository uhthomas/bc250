import os
import unittest

from fast_select_model import assemble
from router_model import SM


class MisoProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pioasm = os.environ.get('PIOASM')
        if not pioasm:
            raise unittest.SkipTest('set PIOASM for assembled MISO probe tests')
        cls.program = assemble(pioasm, 'miso_probe.pio')

    def test_captures_first_reply_after_arm_during_preceding_transaction(self):
        expected = 0x244b4442
        for half in (4, 5, 6):
            for phase in range(5):
                with self.subTest(half=half, phase=phase):
                    sm = SM(self.program, in_base=5, in_count=1)
                    irqs = set()
                    samples = ([0] * (half * 3 + phase) +
                               [1 << 2] * (half * 20))
                    bits = [(0x039dae08 >> shift) & 1 for shift in range(31, -1, -1)]
                    bits += [(expected >> shift) & 1 for shift in range(31, -1, -1)]
                    samples += [0] * (half * 2)
                    for bit in bits:
                        pins = bit << 5
                        samples += [pins] * half + [pins | (1 << 3)] * half
                    samples += [0] * half + [1 << 2] * (half * 4)
                    for pins in samples:
                        sm.step(pins, irqs)
                    self.assertEqual(sm.rx, [expected])
                    self.assertIn(1, irqs)


if __name__ == '__main__':
    unittest.main()
