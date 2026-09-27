import os
import unittest

from fast_reply_model import assemble, replay
from test_capture import waveform


class FastReplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pioasm=os.environ.get('PIOASM')
        if not pioasm:
            raise unittest.SkipTest('set PIOASM for assembled reply tests')
        cls.program=assemble(pioasm)
        cls.rom=bytes(range(256))*(0x1000000//256)
        cls.seq=[((0x03000100+i*4).to_bytes(4,'big')+bytes(4),
                  bytes(4)+cls.rom[0x100+i*4:0x104+i*4]) for i in range(6)]

    def test_slow_control_and_fast_period(self):
        slow=waveform(self.seq,half=16,gap=160)
        self.assertTrue(replay(slow,self.rom,self.program,150000000)['standalone_reply_pass'])
        fast=waveform(self.seq,half=2,gap=54)
        self.assertFalse(replay(fast,self.rom,self.program,150000000)['standalone_reply_pass'])

    def test_early_bit_is_available_at_modeled_480mhz(self):
        fast=waveform(self.seq,half=2,gap=54)
        report=replay(fast,self.rom,self.program,480000000,sync_cycles=3)
        self.assertTrue(report['standalone_reply_pass'],report['reply_errors'])
        self.assertFalse(report['physical_overclock_performed'])


if __name__=='__main__':
    unittest.main()
