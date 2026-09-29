#!/usr/bin/env python3
"""Stage an offline Deck/Cezanne client-12 replay source for RAM-only trials.

Keep the four Cezanne windows required for a BC250 VCN aperture, substitute
the Deck's seven different values, and add its two absent rows. This emits
assembly sources only; it neither signs a ROM nor accesses the board.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

import audit_deck_video_policy as audit


HERE = Path(__file__).resolve().parent
INPUTS = {
    'gasket12-reference.inc': '549cd8965fe04069cc43fe093bc54c2b609d0a640e7c4c4a3c5a3cc3cd4ecd64',
    'tos-entry-gasket12-replay.S': 'ab6d5afce1986fced0ffd00eb8849c86cc7dbfc1b11663db334c7c9eb8883eaa',
    'driver-video-startup.S': '6bb6d7c3cc831df5ca2316a09ea38b75d4064f07c8e3dfc495cd037cba5457c2',
}
REQUIRED_WINDOWS = {
    0x0900c9c4: 0x20108, 0x0900c9c8: 0x20117,
    0x0900c9e8: 0x21078, 0x0900c9ec: 0x2107f,
    0x0900ca0c: 0x20eb0, 0x0900ca10: 0x20eb7,
    0x0900ca30: 0x1f860, 0x0900ca34: 0x1f863,
}


def pinned_source(name):
    data = audit.pinned(HERE / name, INPUTS[name])
    return data.decode()


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise ValueError(f'expected one source span: {before!r}')
    return source.replace(before, after, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()

    bc = audit.pinned(audit.BC_ROM, audit.BC_ROM_SHA)
    deck = audit.pinned(audit.DECK_FD, audit.DECK_FD_SHA)
    deck_sections = audit.policy(
        deck, 0x2a6050, 0x3000, 0x33b750 + 3616,
        'c737ff6822955d6d4bbed201e6b8ab6241dc58adbc1488ff5474975dd4980654')
    # Check the BC policy signature too before borrowing another board's rows.
    audit.policy(bc, 0x982000, 0x2e50, 0x9db4e0,
                 'b365d5b135da12b097a4ef5aecc47a284f1ccd49ac3d251b35b2c0a6de8c9e55')
    deck_rows = [(a, v) for a, v in deck_sections[0x201]
                 if 0x0900c000 <= a < 0x0900d000]
    if len(deck_rows) != 27 or deck_rows[0] != (0x0900c234, 0) or \
            deck_rows[-1] != (0x0900c234, 1):
        raise ValueError('Deck row count changed')

    source_inc = pinned_source('gasket12-reference.inc')
    cezanne_rows = [(int(a, 16), int(v, 16)) for a, v in
                    re.findall(r'\.word 0x([0-9a-f]+), 0x([0-9a-f]+)', source_inc)]
    if len(cezanne_rows) != 51 or cezanne_rows[0] != (0x0900c234, 0) or \
            cezanne_rows[-1] != (0x0900c234, 1):
        raise ValueError('Cezanne replay source changed')
    if any(dict(cezanne_rows).get(a) != v for a, v in REQUIRED_WINDOWS.items()):
        raise ValueError('BC250 aperture-critical windows changed')

    original = dict(cezanne_rows)
    replacements = [(a, original[a], v) for a, v in deck_rows
                    if a != 0x0900c234 and a in original and original[a] != v]
    additions = [(a, v) for a, v in deck_rows if a not in original]
    if len(replacements) != 7 or additions != [
            (0x0900c83c, 0x00ffffe4), (0x0900cdb8, 7)]:
        raise ValueError('unexpected Deck delta')
    deck_by_address = {a: v for a, v in deck_rows if a != 0x0900c234}
    hybrid = [(a, deck_by_address.get(a, v)) for a, v in cezanne_rows]
    hybrid.insert(next(i for i, (a, _) in enumerate(hybrid) if a == 0x0900c838) + 1,
                  additions[0])
    hybrid.insert(next(i for i, (a, _) in enumerate(hybrid) if a == 0x0900cb80) + 1,
                  additions[1])
    if len(hybrid) != 53 or hybrid[0] != (0x0900c234, 0) or \
            hybrid[-1] != (0x0900c234, 1) or \
            any(dict(hybrid).get(a) != v for a, v in REQUIRED_WINDOWS.items()):
        raise ValueError('hybrid table failed structural checks')

    inc = '\n'.join([
        '/* RAM-only BC250 experiment: Deck first-three-window values plus',
        ' * Cezanne windows required for the measured VCN aperture.',
        ' * Not a vendor-signed BC250 policy. NEVER flash this table. */',
        '.equ BC250_GASKET12_ROWS, 53',
        '.balign 4, 0',
        'bc250_gasket12_table:',
        *(f'    .word 0x{a:08x}, 0x{v:08x}' for a, v in hybrid),
        '',
    ])
    tos = pinned_source('tos-entry-gasket12-replay.S')
    tos = replace_once(tos, 'mov r5, #51', 'mov r5, #53')
    tos = replace_once(tos, '#include "gasket12-reference.inc"',
                       '#include "gasket12-deck-hybrid.inc"')
    driver = pinned_source('driver-video-startup.S')
    driver = replace_once(driver, 'movs r5, #51', 'movs r5, #53')
    driver = replace_once(driver, '#include "gasket12-reference.inc"',
                          '#include "gasket12-deck-hybrid.inc"')

    args.output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    generated = {
        'gasket12-deck-hybrid.inc': inc,
        'tos-entry-gasket12-deck-hybrid.S': tos,
        'driver-video-deck-hybrid.S': driver,
    }
    for name, content in generated.items():
        path = args.output_dir / name
        path.write_text(content)
        path.chmod(0o600)
    summary = {
        'signed_deck_policy_verified': True,
        'signed_bc_policy_verified': True,
        'cezanne_rows': 51,
        'deck_rows': 27,
        'hybrid_rows': len(hybrid),
        'deck_replacements': [
            {'address': hex(a), 'cezanne': hex(old), 'deck': hex(new)}
            for a, old, new in replacements],
        'deck_additions': audit.numbered(additions),
        'required_bc250_aperture_windows_retained': True,
        'sources': {name: hashlib.sha256(content.encode()).hexdigest()
                    for name, content in generated.items()},
        'flash_allowed': False,
        'board_access': False,
        'hardware_decode_verified': False,
    }
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
