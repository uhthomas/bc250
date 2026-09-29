#!/usr/bin/env python3
"""Match a TOS-entry PSP memory capture to the pinned BC250 policy parser."""

import argparse
import hashlib
import json
from pathlib import Path
from struct import unpack_from


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    args = parser.parse_args()

    data = args.capture.read_bytes()
    if len(data) != 4096 or data[0x10:0x14] != b'$PS1':
        raise ValueError('expected a 4 KiB PSP memory capture with $PS1 header')
    policies = json.loads(args.reference.read_text())['policies']
    policy = next(item for item in policies
                  if item['name'] == 'BC250 TOS_SECURITY_POLICY')
    count = unpack_from('<I', data, 0x100)[0]
    if count != len(policy['sections']):
        raise ValueError('section count mismatch')

    offset = 0x140
    addresses = []
    for section in policy['sections']:
        tag, length = unpack_from('<II', data, offset)
        offset += 8
        if (tag, length) != (int(section['tag'], 16), section['count']):
            raise ValueError(f"section {section['tag']} header mismatch")
        for record in section['records']:
            address, value = unpack_from('<II', data, offset)
            offset += 8
            if (address, value) != (int(record['word0'], 16),
                                    int(record['word1'], 16)):
                raise ValueError(f"section {section['tag']} record mismatch")
            addresses.append(address)

    print(f'SHA256 {hashlib.sha256(data).hexdigest()}')
    print(f"MATCH {policy['name']} ROM offset {policy['rom_offset']}:",
          f'{count} sections, {len(addresses)} records, parsed end {offset:#x}')
    print('direct 0x0900cxxx VCN policy targets:',
          sum(0x0900c000 <= address < 0x0900d000 for address in addresses))


if __name__ == '__main__':
    main()
