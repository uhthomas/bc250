import struct
import unittest
from capture import HEADER
from qualify_capture import qualify
from test_capture import waveform


class QualifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom=bytes(range(256))*(0x1000000//256)
        cls.seq=[((0x03000000+a).to_bytes(4,'big')+bytes(4),bytes(4)+cls.rom[a:a+4])
                 for a in (0x100,0x104,0x108)]

    def pair(self,seq=None,**kwargs):
        return [waveform(seq or self.seq,half=kwargs.get('half',16),
                         gap=kwargs.get('gap',160)+j,mode=kwargs.get('mode',0)) for j in (0,1)]

    def test_repeat_window_passes_only_digital_screen(self):
        report=qualify(self.pair(),self.rom)
        self.assertTrue(report['digital_envelope_pass'],report['rejection_reasons'])
        self.assertEqual(report['compared_transactions'],3)
        self.assertFalse(report['board_profile_ready'])
        self.assertFalse(report['physical_timing_qualified'])
        self.assertFalse(report['full_boot_coverage'])
        observed=report['observations'][0]
        self.assertAlmostEqual(observed['interval_lower_bounds_ns']['cs_high_before_samples'],1060)
        self.assertEqual(observed['missing_intervals']['cs_high_before_samples'],1)

    def test_conservative_quantization_rejects_nominal_boundary(self):
        report=qualify(self.pair(half=15),self.rom)
        self.assertFalse(report['digital_envelope_pass'])
        self.assertTrue(any('min_half_period_samples' in x for x in report['rejection_reasons']))

    def test_short_high_gap_and_mode3_rejected(self):
        for settings,text in ((dict(gap=100),'cs_high_before_samples'),(dict(mode=3),'idle clock')):
            report=qualify(self.pair(**settings),self.rom)
            self.assertFalse(report['digital_envelope_pass'])
            self.assertTrue(any(text in x for x in report['rejection_reasons']))

    def test_read_order_rom_bytes_and_lengths_checked(self):
        variants=[self.seq[::-1],
                  [self.seq[0],(self.seq[1][0],bytes(8)),self.seq[2]],
                  [self.seq[0],(b'\x9f',bytes(1)),self.seq[2]]]
        for seq in variants:
            report=qualify([self.pair()[0],waveform(seq,half=16,gap=161)],self.rom)
            self.assertFalse(report['digital_envelope_pass'])
            self.assertTrue(any('read order, length or bytes differ' in x for x in report['rejection_reasons']))

    def test_discontinuity_crc_and_skip_cannot_be_ignored(self):
        pair=self.pair()
        flagged=bytearray(pair[1]); struct.pack_into('<I',flagged,24,1)
        report=qualify([pair[0],bytes(flagged)],self.rom)
        self.assertFalse(report['digital_envelope_pass'])
        self.assertTrue(any('discontinuity' in x for x in report['rejection_reasons']))
        different_skip=bytearray(pair[1]); struct.pack_into('<I',different_skip,20,1)
        with self.assertRaisesRegex(ValueError,'same --skip'):
            qualify([pair[0],bytes(different_skip)],self.rom)
        corrupt=pair[1][:-1]+bytes([pair[1][-1]^1])
        with self.assertRaisesRegex(ValueError,'CRC'):
            qualify([pair[0],corrupt],self.rom)

    def test_requires_actual_repeats_and_common_window(self):
        pair=self.pair()
        with self.assertRaisesRegex(ValueError,'two independently'):
            qualify(pair[:1],self.rom)
        with self.assertRaisesRegex(ValueError,'two complete reads'):
            qualify(pair,self.rom,commands=4)
        report=qualify([pair[0],pair[0]],self.rom)
        self.assertFalse(report['digital_envelope_pass'])
        report=qualify([pair[0],waveform(self.seq[:2],half=16,gap=161)],self.rom)
        self.assertTrue(report['digital_envelope_pass'])
        self.assertEqual(report['compared_transactions'],2)
        self.assertEqual(report['observations'][0]['unexamined_complete_tail'],1)
        self.assertFalse(report['full_boot_coverage'])


if __name__=='__main__': unittest.main()
