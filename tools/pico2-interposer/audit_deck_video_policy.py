#!/usr/bin/env python3
"""Compare authenticated BC250 and Steam Deck video-related PSP policy rows.

This is an offline comparison, not evidence that a Deck setting is safe for
Cyan Skillfish or that any observed row starts VCN. It never accesses hardware
or emits a flash image.
"""

import hashlib
import json
from pathlib import Path
import struct

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


ROOT = Path(__file__).resolve().parents[2]
BC_ROM = ROOT / 'output/pico2/tos-entry-noop-20260927/profile/control-NEVER-flash.rom'
BC_ROM_SHA = '2d81a2ed2f07aecbfa0ea1de385243dd500f09059872c6b40072fb96fc2bd6d8'
DECK_FD = ROOT / 'output/video-decode-20260922/sources/steamdeck-keydb-20260925/F7A0016_sign.fd'
DECK_FD_SHA = '00f470140cdff7c73b9f2e0b62a0dc044620b89f8216d319ac4ee01c66e55d1b'
REFERENCE = ROOT / 'output/video-decode-20260922/psp-analysis/security-policy-sections.json'
REFERENCE_SHA = 'b1a07afa24a29c29310dc0b4e7c58ebe71b6a181569f49768979ab9b8108f4d2'
DEST = ROOT / 'output/video-decode-20260922/results/steamdeck-bc250-video-policy-20260929.json'


def pinned(path, digest):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f'pinned input changed: {path}')
    return data


def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def policy(image, start, size, record_start, expected_sha):
    blob = image[start:start + size]
    if hashlib.sha256(blob).hexdigest() != expected_sha:
        raise ValueError(f'policy changed at {start:#x}')
    body_end = 0x100 + u32(blob, 0x14)
    if (blob[0x10:0x14] != b'$PS1' or body_end + 0x100 != len(blob) or
            u32(blob, 0x48) != 0 or u32(blob, 0x50) not in (0, u32(blob, 0x14)) or
            hashlib.sha256(blob[0x100:body_end]).digest() != blob[0xd0:0xf0]):
        raise ValueError('unexpected policy header or digest')
    record = image[record_start:record_start + 0x150]
    if (struct.unpack_from('<4I', record) != (0x150, 1, 31, 65537) or
            blob[0x38:0x48] != record[0x10:0x20]):
        raise ValueError('usage-31 key record changed')
    key = rsa.RSAPublicNumbers(
        65537, int.from_bytes(record[0x50:0x150], 'little')).public_key()
    pss = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)
    key.verify(blob[body_end:], blob[:body_end], pss, hashes.SHA256())
    changed = bytearray(blob[:body_end])
    changed[0x148] ^= 1
    try:
        key.verify(blob[body_end:], changed, pss, hashes.SHA256())
    except InvalidSignature:
        pass
    else:
        raise ValueError('changed policy record retained valid signature')
    n = u32(blob, 0x100)
    if not 0 < n < 64:
        raise ValueError('unexpected section count')
    cursor, sections = 0x140, {}
    for _ in range(n):
        tag, count = struct.unpack_from('<II', blob, cursor)
        end = cursor + 8 + count * 8
        if end > body_end or tag in sections:
            raise ValueError('policy section exceeds signed body or repeats')
        sections[tag] = list(struct.iter_unpack('<II', blob[cursor + 8:end]))
        cursor = end
    if cursor > body_end or any(blob[cursor:body_end]):
        raise ValueError('policy has unexpected trailing content')
    return sections


def numbered(rows):
    return [{'address': hex(a), 'value': hex(v)} for a, v in rows]


def main():
    bc = pinned(BC_ROM, BC_ROM_SHA)
    deck = pinned(DECK_FD, DECK_FD_SHA)
    reference = json.loads(pinned(REFERENCE, REFERENCE_SHA))
    bc_sections = policy(bc, 0x982000, 0x2e50, 0x9db4e0,
                         'b365d5b135da12b097a4ef5aecc47a284f1ccd49ac3d251b35b2c0a6de8c9e55')
    deck_sections = policy(deck, 0x2a6050, 0x3000, 0x33b750 + 3616,
                           'c737ff6822955d6d4bbed201e6b8ab6241dc58adbc1488ff5474975dd4980654')
    deck_tos = policy(deck, 0x333f50, 0x10f0, 0x33b750 + 3616,
                      '62ed079b5f6138de76c52110d23e7afe63794688245d0e8775f9a51ac5994ac8')
    if [len(bc_sections[t]) for t in (0x201, 0x203, 0x210, 0x280, 0x281)] != [
            1230, 31, 13, 100, 31]:
        raise ValueError('BC250 policy layout changed')
    if [len(deck_sections[t]) for t in (0x201, 0x203, 0x280, 0x281)] != [
            1070, 30, 329, 30]:
        raise ValueError('Steam Deck policy layout changed')

    window = lambda rows: [(a, v) for a, v in rows if 0x0900c000 <= a < 0x0900d000]
    bc_video = window(bc_sections[0x201])
    deck_video = window(deck_sections[0x201])
    cezanne = next(p for p in reference['policies'] if p['name'].startswith('cezanne/')
                   and 'SecurePolicyL0' in p['name'])
    cezanne_rows = next(s['records'] for s in cezanne['sections'] if s['tag'] == '0x201')
    cezanne_video = window([(int(r['word0'], 16), int(r['word1'], 16))
                            for r in cezanne_rows])
    if len(bc_video) != 0 or len(deck_video) != 27 or len(cezanne_video) != 51:
        raise ValueError('video-window geometry changed')
    deck_only = [row for row in deck_video if row not in cezanne_video]
    if len(deck_only) != 9:
        raise ValueError('Deck/Cezanne policy overlap changed')
    cezanne_by_address = {a: v for a, v in cezanne_video}
    deck_replacements = [
        {'address': hex(a), 'cezanne': hex(cezanne_by_address[a]), 'deck': hex(v)}
        for a, v in deck_only if a in cezanne_by_address
    ]
    deck_additions = [(a, v) for a, v in deck_only if a not in cezanne_by_address]
    if len(deck_replacements) != 7 or len(deck_additions) != 2:
        raise ValueError('unexpected Deck/Cezanne row delta geometry')
    bc_setup = [v for a, v in bc_sections[0x201] if a == 0x1f8a4]
    deck_setup = [v for a, v in deck_sections[0x201] if a == 0x1f8a4]
    if bc_setup != [0xb] or deck_setup != [0xf] or \
            [v for a, v in deck_tos[0x210] if a == 0x1f8a4] != [0xf]:
        raise ValueError('0x1f8a4 reference values changed')

    report = {
        'inputs': {'bc_rom_sha256': BC_ROM_SHA, 'deck_fd_sha256': DECK_FD_SHA,
                   'reference_json_sha256': REFERENCE_SHA},
        'signatures': {'bc250_sec_gasket': 'verified under BC250 usage-31 key',
                       'deck_sec_gasket': 'verified under Deck usage-31 key',
                       'deck_tos_policy': 'verified under Deck usage-31 key',
                       'changed_record_negative_controls': 'rejected'},
        'client12_0x0900cxxx': {
            'bc250_records': len(bc_video),
            'deck_records': len(deck_video),
            'cezanne_records': len(cezanne_video),
            'deck_exact_rows_shared_with_cezanne': len(deck_video) - len(deck_only),
            'deck_replacements_of_cezanne_rows': deck_replacements,
            'deck_rows_absent_from_cezanne': numbered(deck_additions),
            'deck_rows_not_in_cezanne': numbered(deck_only),
            'deck_rows': numbered(deck_video),
        },
        'early_0x1f8a4': {'bc250': hex(bc_setup[0]),
                          'steam_deck': hex(deck_setup[0]),
                          'difference_xor': hex(bc_setup[0] ^ deck_setup[0])},
        'interpretation_limit': 'Signed policy differences identify test candidates, '
            'not a VCN start control. The earlier BC250 Cezanne/Renoir 51-row '
            'replay did not produce a running VCPU, and Steam Deck uses a '
            'different SoC and firmware policy.',
        'board_access': False, 'flash_written': False,
        'hardware_decode_verified': False,
    }
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'client12_0x0900cxxx'},
                     indent=2))
    print(f'Full comparison: {DEST}')


if __name__ == '__main__':
    main()
