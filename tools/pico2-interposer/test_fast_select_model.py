import collections
import os
import unittest

from fast_select_model import assemble, replay
from router_model import SM
from test_capture import waveform


class FastSelectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pioasm = os.environ.get('PIOASM')
        if not pioasm:
            raise unittest.SkipTest('set PIOASM for assembled selector tests')
        cls.program = assemble(pioasm)
        cls.rom = bytes(range(256)) * (0x1000000 // 256)
        cls.sequence = [((0x03000100 + 4*i).to_bytes(4, 'big') + bytes(4),
                         bytes(4) + cls.rom[0x100+4*i:0x104+4*i]) for i in range(7)]

    def test_pass_and_patch_share_one_sm_at_modeled_200mhz(self):
        blob = waveform(self.sequence, half=2, gap=54, cs_setup=7)
        for patch_index in range(6):
            for sync in (2, 3):
                for phase in range(5):
                    with self.subTest(patch_index=patch_index, sync=sync, phase=phase):
                        result = replay(blob, self.rom, self.program, 200000000,
                                        start_index=1, patch_index=patch_index,
                                        sync_cycles=sync, phase_fifths=phase)
                        self.assertTrue(result['pass_model'], result['errors'])
                        self.assertGreaterEqual(result['minimum_modeled_flash_cs_setup_ns'], 100)

    def test_empty_fifo_deselects_flash_and_miso(self):
        sm = SM(self.program, collections.deque())
        state = dict(flash_cs=1, oe=0)
        for pins in [4]*20 + [0]*200 + [4]*20:
            state.update(sm.step(pins, set()))
            self.assertEqual(state['flash_cs'], 1)
            self.assertEqual(state['oe'], 0)


if __name__ == '__main__':
    unittest.main()
