#!/usr/bin/env python3
"""Audit pinned BC250 PSP-directory inputs and their captured SPI read order.

The trace establishes read order, not execution order or register causality.
This script neither modifies firmware nor accesses hardware.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
from struct import unpack_from


ROM_SHA = 'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183'
PROFILE_SHA = 'f1a0c46b57e052f7943f7ab95e678fc3338ca16beaa21f6cabada54b489d7851'
POLICY_SHA = 'b1a07afa24a29c29310dc0b4e7c58ebe71b6a181569f49768979ab9b8108f4d2'
IPL_SHA = '2fe1046cb0ac338d86176bf59e8fdabd574954d1df5892fd8c674e40a2309141'
DIRECTORIES = ((0x8e0000, b'$PSP', 19), (0xab0000, b'$BHD', 4))
OBJECT_TYPES = {0x08: 'SMU_OFFCHIP_FW', 0x0b: 'SOFT_FUSE_CHAIN_01',
                0x20: 'HARDWARE_IP_CONFIG', 0x24: 'SEC_GASKET',
                0x30: 'ABL0', 0x45: 'TOS_SECURITY_POLICY', 0x60: 'APCB'}
TARGETS = (0x1f81c, 0x1f820, 0x1f8a4)
APCB_GROUPS = (b'PSPG', b'CCXG', b'DFG ', b'MEMG', b'GNBG', b'FCHG', b'CBSG')


def checked(path: Path, expected_sha: str) -> bytes:
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha:
        raise ValueError(f'{path}: SHA256 {actual}, expected {expected_sha}')
    return data


def directories(rom: bytes) -> list[dict]:
    result = []
    for offset, magic, expected_count in DIRECTORIES:
        if rom[offset:offset + 4] != magic:
            raise ValueError(f'{offset:#x}: unexpected directory magic')
        count = unpack_from('<I', rom, offset + 8)[0]
        if count != expected_count:
            raise ValueError(f'{offset:#x}: {count} entries, expected {expected_count}')
        for index in range(count):
            kind, size, raw_address, _ = unpack_from('<IIII', rom, offset + 0x10 + index * 16)
            address = raw_address & 0xffffff
            if raw_address not in (0, 0xffffffff) and size != 0xffffffff and \
                    address + size > len(rom):
                raise ValueError(f'{offset:#x} entry {index}: out of ROM bounds')
            result.append({'directory': hex(offset), 'index': index,
                           'type': hex(kind), 'name': OBJECT_TYPES.get(kind, ''),
                           'address': hex(address), 'size': size})
    return result


def runs(profile: str) -> list[tuple[int, int]]:
    marker = 'static const struct expected_run expected_runs[PROFILE_RUNS] = {'
    body = profile.split(marker, 1)[1].split('};', 1)[0]
    result = [(int(address, 16) & 0xffffff, int(words)) for address, words in
              re.findall(r'\{0x([0-9a-f]+)u, (\d+)u\}', body)]
    if len(result) != 37 or sum(count for _, count in result) != 872744:
        raise ValueError('pinned SPI read profile changed')
    return result


def read_rows(trace: list[tuple[int, int]], start: int, end: int) -> list[dict]:
    matches = []
    row = 0
    for address, count in trace:
        if address < end and address + count * 4 > start:
            matches.append({'row': row, 'address': hex(address), 'words': count})
        row += count
    return matches


def policy_targets(policy_data: dict) -> list[dict]:
    matches = []
    for policy in policy_data['policies']:
        if not policy['name'].startswith('BC250 '):
            continue
        for section in policy['sections']:
            for index, record in enumerate(section['records']):
                address = int(record['word0'], 16)
                if address in TARGETS:
                    matches.append({'policy': policy['name'], 'section': section['tag'],
                                    'row': index, 'address': hex(address),
                                    'value': record['word1']})
    return matches


def apcb_summary(rom: bytes) -> dict:
    apcb = rom[0xab1000:0xab3000]
    if apcb[:4] != b'APCB' or unpack_from('<HH', apcb, 4) != (0x20, 0x20):
        raise ValueError('unexpected BC250 APCB header')
    total = unpack_from('<I', apcb, 8)[0]
    if not 0x20 <= total <= len(apcb) or sum(apcb[:total]) & 0xff:
        raise ValueError('BC250 APCB size or checksum invalid')
    found = [magic.decode().strip() for magic in APCB_GROUPS
             if apcb.find(magic, 0x20, total) >= 0]
    absent = [magic.decode().strip() for magic in APCB_GROUPS
              if magic.decode().strip() not in found]
    return {'sha256': hashlib.sha256(apcb).hexdigest(), 'total_size': total,
            'checksum_valid': True, 'known_groups_present': found,
            'known_groups_absent': absent}


def ipl_table_summary(ipl: bytes) -> dict:
    offset = unpack_from('<I', ipl, 0x5d54)[0]
    if offset != 0x8928 or ipl[0x95a4] != 1:
        raise ValueError('decrypted IPL embedded-table location changed')
    rows = [unpack_from('<II', ipl, offset + index * 8) for index in range(0x58)]
    if rows[0][0] != 0x0902f910 or rows[-1][0] != 0x0900bb2c:
        raise ValueError('decrypted IPL embedded-table endpoints changed')
    targets = TARGETS + (0x50d6c, 0x511b4)
    matches = [{'row': index, 'address': hex(address), 'value': hex(value)}
               for index, (address, value) in enumerate(rows) if address in targets]
    return {'table_offset': hex(offset), 'rows': len(rows),
            'named_direct_target_matches': matches}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--policies', type=Path, required=True)
    parser.add_argument('--ipl', type=Path, required=True)
    args = parser.parse_args()
    rom = checked(args.rom, ROM_SHA)
    trace = runs(checked(args.profile, PROFILE_SHA).decode())
    policies = json.loads(checked(args.policies, POLICY_SHA))
    ipl = checked(args.ipl, IPL_SHA)
    entries = directories(rom)
    selected = []
    for entry in entries:
        if entry['name']:
            selected.append({**entry, 'reads': read_rows(
                trace, int(entry['address'], 16), int(entry['address'], 16) + entry['size'])})
    print(json.dumps({
        'rom_sha256': ROM_SHA,
        'profile_sha256': PROFILE_SHA,
        'policy_sha256': POLICY_SHA,
        'ipl_sha256': IPL_SHA,
        'directory_offsets': [hex(offset) for offset, _, _ in DIRECTORIES],
        'soft_fuse_chain_01_present_in_parsed_directories': any(
            entry['type'] == '0xb' for entry in entries),
        'selected_entries': selected,
        'apcb': apcb_summary(rom),
        'ipl_embedded_smn_table': ipl_table_summary(ipl),
        'bc250_direct_policy_targets': policy_targets(policies),
        'limitation': 'Captured SPI read order is not code execution order; absence of a '
                      'type-0x0b entry does not rule out hardware-provisioned fuses or '
                      'other configuration sources.',
    }, indent=2))


if __name__ == '__main__':
    main()
