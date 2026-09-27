#!/usr/bin/env python3
"""Extract the matching Cezanne/Renoir client-12 policy records for a RAM trial.

This makes no claim that these records are safe BC250 production settings.
The output is a signed-driver code-cave input, never an EEPROM image.
"""
import argparse
import hashlib
import json
from pathlib import Path


POLICY_JSON_SHA = 'b1a07afa24a29c29310dc0b4e7c58ebe71b6a181569f49768979ab9b8108f4d2'
CEZANNE_SHA = '39f398f50499eef85abdf3b18dcd2cb0a2cf26fb3684318f6bf9a4e40d282740'
RENOIR_SHA = 'cd714e3e3fad7a664c79b9b90ddfe0e6bec18a4715fb150ece615abb08eee6a7'
LO, HI = 0x0900c000, 0x0900d000


def records(policy):
    section = next(item for item in policy['sections'] if item['tag'] == '0x201')
    return [(int(row['word0'], 16), int(row['word1'], 16))
            for row in section['records']
            if LO <= int(row['word0'], 16) < HI]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policies', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.policies.read_bytes()
    assert hashlib.sha256(source).hexdigest() == POLICY_JSON_SHA
    policies = json.loads(source)['policies']
    bc250 = next(p for p in policies if p['name'] == 'BC250 SEC_GASKET')
    cezanne = next(p for p in policies if p['name'].startswith('cezanne/') and
                   'SecurePolicyL0' in p['name'])
    renoir = next(p for p in policies if p['name'].startswith('v2000a/') and
                  p['name'].endswith('PspBl.sbin'))
    assert not records(bc250)
    assert cezanne['sha256'] == CEZANNE_SHA and renoir['sha256'] == RENOIR_SHA
    rows = records(cezanne)
    assert len(rows) == 51 and rows == records(renoir)
    assert rows[0] == (0x0900c234, 0) and rows[-1] == (0x0900c234, 1)
    assert len(set(address for address, _ in rows)) == 50
    lines = [
        '/* RAM-only experiment: identical Cezanne/Renoir client-12 policy rows.',
        f' * Source policy JSON SHA-256: {POLICY_JSON_SHA}',
        ' * BC250 SEC_GASKET has no 0x0900cxxx row. Never flash this table. */',
        '.equ BC250_GASKET12_ROWS, 51',
        '.balign 4, 0',
        'bc250_gasket12_table:',
    ]
    lines += [f'    .word 0x{address:08x}, 0x{value:08x}'
              for address, value in rows]
    args.output.write_text('\n'.join(lines) + '\n')
    print(f'Extracted {len(rows)} identical reference records to {args.output}')


if __name__ == '__main__':
    main()
