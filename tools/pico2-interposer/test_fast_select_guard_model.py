import os
import unittest

from fast_select_model import assemble, replay
from test_capture import waveform


class FastSelectGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pioasm = os.environ.get('PIOASM')
        if not pioasm:
            raise unittest.SkipTest('set PIOASM for assembled guarded-selector tests')
        cls.program = assemble(pioasm, 'fast_select_guard.pio')
        cls.rom = bytes(range(256)) * (0x1000000 // 256)
        reads = [((0x03000100 + 4 * i).to_bytes(4, 'big') + bytes(4),
                  bytes(4) + cls.rom[0x100 + 4 * i:0x104 + 4 * i])
                 for i in range(7)]
        cls.blob = waveform(reads, half=2, gap=54, cs_setup=7)

    def test_correct_command_enables_reply_at_340mhz(self):
        for sync in (2, 3):
            for phase in range(5):
                with self.subTest(sync=sync, phase=phase):
                    result = replay(self.blob, self.rom, self.program, 340000000,
                                    start_index=1, sync_cycles=sync,
                                    phase_fifths=phase, guarded=True)
                    self.assertTrue(result['pass_model'], result['errors'])
                    self.assertFalse(result['fault_irq_raised'])

    def test_wrong_command_never_enables_miso_and_latches_fault(self):
        for sync in (2, 3):
            for phase in range(5):
                with self.subTest(sync=sync, phase=phase):
                    result = replay(self.blob, self.rom, self.program, 340000000,
                                    start_index=1, sync_cycles=sync,
                                    phase_fifths=phase, guarded=True,
                                    corrupt_expected_patch=True)
                    self.assertTrue(result['pass_model'], result['errors'])
                    self.assertTrue(result['fault_irq_raised'])


if __name__ == '__main__':
    unittest.main()
