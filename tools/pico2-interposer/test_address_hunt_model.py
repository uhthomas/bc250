import os
import unittest

from address_hunt_model import assemble,replay
from test_capture import waveform


class HuntPIOTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        executable=os.environ.get('PIOASM')
        if not executable:raise unittest.SkipTest('set PIOASM to test assembled hunter')
        cls.program=assemble(executable)
        cls.rom=bytes(range(256))*(0x1000000//256)
        cls.seq=[((0x03000100+i*4).to_bytes(4,'big')+bytes(4),
                  bytes(4)+cls.rom[0x100+i*4:0x104+i*4]) for i in range(6)]

    def test_slow_and_four_samples_per_clock(self):
        for half in (16,2):
            with self.subTest(half=half):
                blob=waveform(self.seq,half=half,gap=54)
                result=replay(blob,self.rom,self.program,sync_cycles=2)
                self.assertTrue(result['matched'],result)
                self.assertFalse(result['PIO_outputs_present'])


if __name__=='__main__':unittest.main()
