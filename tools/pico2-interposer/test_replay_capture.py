import os
import unittest

from replay_capture import replay
from router_model import assemble
from test_capture import waveform


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        exe = os.environ.get('PIOASM')
        if not exe:
            raise unittest.SkipTest('set PIOASM for recorded-edge replay tests')
        cls.programs = assemble(exe)
        cls.rom = bytes(range(256)) * (0x1000000//256)
        cls.seq = [((0x03000100+i*4).to_bytes(4,'big')+bytes(4),
                    bytes(4)+cls.rom[0x100+i*4:0x104+i*4]) for i in range(6)]

    def test_supported_waveform_patches_and_passes(self):
        report = replay(waveform(self.seq,half=16,gap=160),self.rom,self.programs,150000000)
        self.assertTrue(report['pio_replay_pass'],report)
        self.assertEqual(report['clock_counts'],[64]*6)
        self.assertFalse(report['physical_overclock_performed'])

    def test_fast_waveform_fails_and_release_time_does_not_shrink(self):
        blob = waveform(self.seq,half=2,gap=54)
        report = replay(blob,self.rom,self.programs,150000000)
        self.assertFalse(report['pio_replay_pass'])
        faster = replay(blob,self.rom,self.programs,480000000)
        self.assertEqual(faster['flash_release_assumption_ns'],report['flash_release_assumption_ns'])
        self.assertGreaterEqual(faster['flash_release_cycles']*1e9/480000000,40/3)


if __name__ == '__main__':
    unittest.main()
