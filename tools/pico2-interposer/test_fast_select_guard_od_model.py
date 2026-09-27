import os
import unittest

from fast_select_model import assemble, replay
from test_capture import waveform


class OpenDrainGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pioasm = os.environ.get('PIOASM')
        if not pioasm:
            raise unittest.SkipTest('set PIOASM for assembled open-drain guard tests')
        cls.program = assemble(pioasm, 'fast_select_guard_od.pio')
        cls.rom = bytes(range(256)) * (0x1000000 // 256)
        reads = [((0x03000100 + 4 * i).to_bytes(4, 'big') + bytes(4),
                  bytes(4) + cls.rom[0x100 + 4 * i:0x104 + 4 * i])
                 for i in range(7)]
        cls.blob = waveform(reads, half=2, gap=54, cs_setup=7)

    def test_cs_program_only_changes_direction_and_fits_pio(self):
        instructions = [int(i['hex'], 16) for i in self.program['instructions']]
        self.assertLessEqual(len(instructions), 32)
        set_destinations = [(ins >> 5) & 7 for ins in instructions if ins >> 13 == 7]
        self.assertTrue(set_destinations)
        self.assertNotIn(0, set_destinations)  # no SET PINS high/low
        self.assertIn(4, set_destinations)     # SET PINDIRS release/sink

    def test_guarded_patch_and_negative_command(self):
        for corrupt in (False, True):
            for sync in (2, 3):
                for phase in range(5):
                    with self.subTest(corrupt=corrupt, sync=sync, phase=phase):
                        result = replay(self.blob, self.rom, self.program,
                                        340000000, start_index=1,
                                        sync_cycles=sync, phase_fifths=phase,
                                        guarded=True,
                                        corrupt_expected_patch=corrupt)
                        self.assertTrue(result['pass_model'], result['errors'])
                        self.assertEqual(result['fault_irq_raised'], corrupt)


if __name__ == '__main__':
    unittest.main()
