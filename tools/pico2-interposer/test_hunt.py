import unittest
from hunt import parse_hits


class HuntHostTests(unittest.TestCase):
    def test_scoped_hits_keep_transaction_indices(self):
        result=parse_hits('HITS seen=1000 kept=2 overflow=0 stall=0 cancelled=0',
                          ['123 039dad00','999 039db140'],'DONEH',0x9dad00,0x9dc240)
        self.assertTrue(result['usable_for_ordering'])
        self.assertEqual([h['transaction'] for h in result['hits']],[123,999])

    def test_overflow_stall_and_order_fail_closed(self):
        for header in ('HITS seen=1000 kept=1 overflow=1 stall=0 cancelled=0',
                       'HITS seen=1000 kept=1 overflow=0 stall=1 cancelled=0'):
            result=parse_hits(header,['123 039dad00'],'DONEH',0x9dad00,0x9dc240)
            self.assertFalse(result['usable_for_ordering'])
        for records,footer in ((['123 039dad00','122 039dad04'],'DONEH'),
                               (['123 039dad00','125 039dc240'],'DONEH'),
                               (['123 039dad00','124 039dad04'],'BAD')):
            with self.assertRaises(ValueError):
                parse_hits('HITS seen=1000 kept=2 overflow=0 stall=0 cancelled=0',
                           records,footer,0x9dad00,0x9dc240)


if __name__=='__main__':unittest.main()
