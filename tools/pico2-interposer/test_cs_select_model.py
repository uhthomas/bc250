import os
import unittest

from cs_select_model import assemble, replay
from router_model import SM
from test_capture import waveform


class SelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pioasm = os.environ.get('PIOASM')
        if not pioasm:
            raise unittest.SkipTest('set PIOASM for assembled selector tests')
        cls.program = assemble(pioasm)
        cls.rom = bytes(range(256)) * (0x1000000 // 256)
        cls.sequence = [((0x03000100 + 4*i).to_bytes(4, 'big') + bytes(4),
                         bytes(4) + cls.rom[0x100+4*i:0x104+4*i])
                        for i in range(7)]

    def test_preselected_patch_keeps_flash_deselected(self):
        # The board's sampled CS-to-first-clock setup is 6–7 samples even
        # though its SPI half-period is only 2–3 samples.
        blob = waveform(self.sequence, half=2, gap=54, cs_setup=7)
        for sync in (2, 3):
            for phase in range(5):
                with self.subTest(sync=sync, phase=phase):
                    result = replay(blob, self.rom, self.program, 200000000,
                                    start_index=1, sync_cycles=sync,
                                    phase_fifths=phase)
                    self.assertTrue(result['pass_model'], result['errors'])
                    self.assertGreaterEqual(result['minimum_modeled_flash_cs_setup_ns'], 3)

    def test_empty_route_fifo_leaves_original_flash_deselected(self):
        sm = SM(self.program)
        flash_cs = 1
        for pins in [4]*20 + [0]*200 + [4]*20:
            change = sm.step(pins, set())
            flash_cs = change.get('flash_cs', flash_cs)
            self.assertEqual(flash_cs, 1)


if __name__ == '__main__':
    unittest.main()
