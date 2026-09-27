import struct
import unittest
import zlib
from capture import HEADER, MAGIC, decode, unpack


def waveform(transactions, mode=0, half=4, gap=16, cs_setup=None):
    idle = 1 | (2 if mode == 3 else 0)
    s = [idle] * 16
    for tx, rx in transactions:
        s += [idle & ~1] * (half if cs_setup is None else cs_setup)
        for a, b in zip(tx, rx):
            for bit in range(7, -1, -1):
                v = ((a >> bit & 1) << 2) | ((b >> bit & 1) << 3)
                s += [v] * half + [v | 2] * half
        s += [idle & ~1] * half + [idle] * gap
    s += [idle] * (-len(s) % 8)
    payload = bytes(s[i] | s[i+1] << 4 for i in range(0, len(s), 2))
    return HEADER.pack(MAGIC, len(payload)//4, 150000000, 1, 0, 0,
                       zlib.crc32(payload)) + payload


class CaptureTests(unittest.TestCase):
    def test_both_modes_and_rom_bytes(self):
        tx = bytes.fromhex('0300001000000000')
        rx = bytes.fromhex('00000000a501ff80')
        rom = bytes(16) + rx[4:]
        for mode in (0, 3):
            r = decode(waveform([(tx,rx)], mode), rom)
            self.assertEqual(r['summary']['read03_four_byte'], 1)
            self.assertEqual(r['summary']['rom_mismatches'], 0)
            self.assertEqual(r['transactions'][0]['data_hex'], 'a501ff80')
            self.assertEqual(r['summary']['median_clock_hz'], 18750000)
            self.assertEqual(r['summary']['warnings'], [])
            self.assertEqual(r['transactions'][0]['idle_clock'],int(mode==3))

    def test_cs_and_clock_intervals(self):
        seq=[(bytes.fromhex('0300000000000000'),bytes(8))]*2
        rows=decode(waveform(seq,half=16,gap=160))['transactions']
        self.assertEqual(rows[0]['cs_setup_samples'],32)
        self.assertEqual(rows[0]['cs_hold_samples'],16)
        self.assertEqual(rows[0]['min_period_samples'],32)
        self.assertEqual(rows[0]['min_half_period_samples'],16)
        self.assertIsNone(rows[0]['cs_high_before_samples'])
        self.assertEqual(rows[1]['cs_high_before_samples'],160)

    def test_fractional_sample_period_frequency(self):
        # A clock near one cycle per 4.5 samples must not be reported solely
        # by the median of its rounded four/five-sample periods.
        rises = [20 + i*9//2 for i in range(64)]
        samples = [1]*16 + [0]*(rises[-1]+6-16) + [1]*16
        for rise in rises:
            samples[rise:rise+2] = [2, 2]
        samples += [1]*(-len(samples)%8)
        data = bytes(samples[i] | samples[i+1]<<4 for i in range(0,len(samples),2))
        blob = HEADER.pack(MAGIC,len(data)//4,150000000,1,0,0,zlib.crc32(data))+data
        summary = decode(blob)['summary']
        self.assertEqual(summary['complete_transactions'],1)
        self.assertEqual(summary['period_samples_histogram'],{4:32,5:31})
        self.assertAlmostEqual(summary['mean_clock_hz'],150000000*63/283)

    def test_simultaneous_cs_clock_deassertion_is_unresolved(self):
        blob=waveform([(bytes.fromhex('0300000000000000'),bytes(8))])
        _,payload=unpack(blob)
        samples=[n for byte in payload for n in (byte&15,byte>>4)]
        end=decode(blob)['transactions'][0]['end_sample']
        # Remove the final falling-clock edge until the CS-rise sample.
        for i in range(end-4,end): samples[i]|=2
        data=bytes(samples[i]|samples[i+1]<<4 for i in range(0,len(samples),2))
        fields=list(HEADER.unpack_from(blob)); fields[-1]=zlib.crc32(data)
        result=decode(HEADER.pack(*fields)+data)
        self.assertTrue(result['summary']['sampled_edge_ambiguities'])

    def test_short_transaction_does_not_corrupt_next(self):
        seq = [(b'\x9f', b'\x00'),
               (bytes.fromhex('0300000000000000'), bytes.fromhex('0000000001020304'))]
        r = decode(waveform(seq), b'\x01\x02\x03\x04')
        self.assertEqual(r['summary']['complete_transactions'], 2)
        self.assertEqual(r['summary']['read03_four_byte'], 1)
        self.assertEqual(r['summary']['rom_mismatches'], 0)

    def test_wrong_rom(self):
        r = decode(waveform([(bytes.fromhex('0300000000000000'), bytes(8))]), b'bad!')
        self.assertEqual(r['summary']['rom_mismatches'], 1)

    def test_corruption_and_lengths(self):
        b = waveform([(b'\x9f', b'\x12')])
        with self.assertRaisesRegex(ValueError, 'CRC'):
            unpack(b[:-1] + bytes([b[-1] ^ 1]))
        for broken in (b[:8], b[:-4], b + b'\x00'):
            with self.assertRaises(ValueError): unpack(broken)

    def test_undersampling_and_stall_reported(self):
        b = bytearray(waveform([(b'\xaa', b'\x55')], half=1))
        struct.pack_into('<I', b, 24, 1)
        r = decode(bytes(b))
        self.assertTrue(any('margin' in w for w in r['summary']['warnings']))
        self.assertTrue(any('discontinuity' in w for w in r['summary']['warnings']))


if __name__ == '__main__':
    unittest.main()
