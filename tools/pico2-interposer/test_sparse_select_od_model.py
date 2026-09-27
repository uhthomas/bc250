import os
import unittest

from fast_select_model import assemble, replay
from test_capture import waveform


class SparseOpenDrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pioasm = os.environ.get('PIOASM')
        if not pioasm:
            raise unittest.SkipTest('set PIOASM for assembled sparse selector tests')
        cls.program = assemble(pioasm, 'sparse_select_od.pio')
        cls.rom = bytes(range(256)) * (0x1000000 // 256)
        reads = [((0x03000100 + 4 * i).to_bytes(4, 'big') + bytes(4),
                  bytes(4) + cls.rom[0x100 + 4 * i:0x104 + 4 * i])
                 for i in range(7)]
        # 25 MHz is faster than the measured 0x9db140 key read (~17 MHz).
        cls.blob = waveform(reads, half=3, gap=54, cs_setup=7)

    def test_program_releases_or_sinks_cs_only(self):
        instructions = [int(i['hex'], 16) for i in self.program['instructions']]
        self.assertLessEqual(len(instructions), 32)
        destinations = [(ins >> 5) & 7 for ins in instructions if ins >> 13 == 7]
        self.assertNotIn(0, destinations)
        self.assertIn(4, destinations)

    def test_sparse_patch_after_preceding_command_and_fault(self):
        for corrupt in (False, True):
            for sync in (2, 3):
                for phase in range(5):
                    with self.subTest(corrupt=corrupt, sync=sync, phase=phase):
                        result = replay(self.blob, self.rom, self.program,
                                        340000000, start_index=1,
                                        sync_cycles=sync, phase_fifths=phase,
                                        guarded=True, sparse_default_pass=True,
                                        corrupt_expected_patch=corrupt)
                        self.assertTrue(result['pass_model'], result['errors'])
                        self.assertEqual(result['fault_irq_raised'], corrupt)


if __name__ == '__main__':
    unittest.main()
