import unittest

from cs_pass_stream import parse_chunk_header, parse_done


class StreamFramingTests(unittest.TestCase):
    def test_chunk_and_final_counters(self):
        self.assertEqual(parse_chunk_header('CHNK 256 deadbeef'), (256, 0xdeadbeef))
        done = parse_done('DONE seen=513 sent=512 records=2 overflow=1 stall=0 cancelled=0', 2, 512)
        self.assertFalse(done['usable_for_ordering'])
        self.assertEqual(done['overflow'], 1)

    def test_invalid_framing_is_rejected(self):
        for line in ('CHNK 0 00000000', 'CHNK 257 00000000', 'CHNK 1 fffffffff'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_chunk_header(line)
        with self.assertRaises(ValueError):
            parse_done('DONE seen=513 sent=512 records=2 overflow=0 stall=0 cancelled=0', 2, 512)


if __name__ == '__main__':
    unittest.main()
