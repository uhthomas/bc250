import os
import unittest

from fast_select_model import assemble, replay
from test_capture import waveform


class EarlySparseSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pioasm = os.environ.get('PIOASM')
        if not pioasm:
            raise unittest.SkipTest('set PIOASM for assembled early selector tests')
        cls.program = assemble(pioasm, 'sparse_select_early.pio')
        cls.rom = bytes(range(256)) * (0x1000000 // 256)
        reads = [((0x03000100 + 4 * i).to_bytes(4, 'big') + bytes(4),
                  bytes(4) + cls.rom[0x100 + 4 * i:0x104 + 4 * i])
                 for i in range(7)]
        # 25 MHz is faster than the measured 0x9db140 key read (~17 MHz).
        cls.blob = waveform(reads, half=3, gap=54, cs_setup=7)

    def test_early_output_only_during_final_command_bit_and_correct_reply(self):
        self.assertLessEqual(len(self.program['instructions']), 32)
        for corrupt in (False, True):
            for sync in (2, 3):
                for phase in range(5):
                    with self.subTest(corrupt=corrupt, sync=sync, phase=phase):
                        result = replay(self.blob, self.rom, self.program,
                                        340000000, start_index=1,
                                        sync_cycles=sync, phase_fifths=phase,
                                        guarded=True, sparse_default_pass=True,
                                        corrupt_expected_patch=corrupt,
                                        early_command_drive=True)
                        self.assertTrue(result['pass_model'], result['errors'])
                        self.assertEqual(result['fault_irq_raised'], corrupt)


if __name__ == '__main__':
    unittest.main()
