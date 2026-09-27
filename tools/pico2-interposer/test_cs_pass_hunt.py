import unittest

from cs_pass_hunt import parse


class PassHuntParserTests(unittest.TestCase):
    def test_valid_predecessor_context(self):
        result = parse('HITS seen=100 kept=2 overflow=0 stall=0 cancelled=0',
                       ['10 038f0900 038f08fc 038f08f8',
                        '11 038f0904 038f0900 038f08fc'], 'DONEH')
        self.assertTrue(result['usable_for_ordering'])
        self.assertEqual(result['hits'][1]['previous'], '038f0900')

    def test_incomplete_capture_cannot_be_used_for_ordering(self):
        result = parse('HITS seen=100 kept=1 overflow=3 stall=0 cancelled=0',
                       ['10 038f0900 038f08fc 038f08f8'], 'DONEH')
        self.assertFalse(result['usable_for_ordering'])
        with self.assertRaisesRegex(ValueError, 'out-of-order'):
            parse('HITS seen=100 kept=2 overflow=0 stall=0 cancelled=0',
                  ['10 038f0900 0 0', '10 038f0904 0 0'], 'DONEH')


if __name__ == '__main__':
    unittest.main()
