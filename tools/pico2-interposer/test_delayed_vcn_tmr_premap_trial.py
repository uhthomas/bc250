#!/usr/bin/env python3
"""Execute the signed PSP TMR-prefix read hook with native ARM instructions."""

import argparse
import hashlib
from pathlib import Path
import struct

import postload_model as model
import prepare_video_driver_trial as video


DRIVER = 0x984f00
DRIVER_LEN = 0x1a770
POWER = 0x1f810
SCRATCH = 0x1f854
RESET = 0x20180
TMR = 0xf41fa00000
CONTROL = 0xf400162ec0
PAYLOAD_WORDS = (0x45574f50, 0x20444552, 0x41205942, 0x0a0d444d)
PAYLOAD = struct.pack('<4I', *PAYLOAD_WORDS)
RESULTS = {0x0900c004: 0, 0x1f8a4: 0, RESET: 0,
           **dict.fromkeys(dict(video.EXPECTED_MAP), 0)}
NORMAL_WRITES = ['0x900c004', '0x1f8a4'] + [hex(addr) for addr, _ in video.EXPECTED_MAP] + [hex(RESET)]
PREMAP_WRITES = NORMAL_WRITES[:2]


def run(driver: bytes, payload: bytes, map_result: int,
        expected_result: int, target: int, attr: int) -> None:
    row = model.run_case(0xffff, RESULTS, 0, 0, driver_override=driver,
                         loaded_before=1, expected_result=expected_result,
                         readbacks={POWER: (0, 0x800),
                                    SCRATCH: (0, 0x5a13c0df)},
                         expected_smn_addresses=PREMAP_WRITES,
                         extra_mapping=(target, map_result, payload, attr))
    maps = [event for event in row['events'] if event.get('stub') == 'map_buffer']
    assert maps == [{'stub': 'map_buffer', 'address': hex(target),
                     'bytes': 4096, 'result': hex(map_result)}], maps
    unmaps = [event for event in row['events'] if event.get('stub_svc') == '0x6c']
    assert len(unmaps) == (map_result == 0), unmaps
    assert [event['address'] for event in row['events']
            if event.get('stub_svc') == '0x7b'] == [hex(POWER), hex(SCRATCH)]
    assert not row['writes'], row['writes']


def check(driver: bytes, target: int, attr: int) -> int:
    cases = 0
    run(driver, PAYLOAD, 0, 0x75000004, target, attr)
    cases += 1

    for index in range(4):
        values = list(PAYLOAD_WORDS)
        values[index] ^= 0x00100001
        result = 0x76000000 | (index << 20) | (values[index] & 0xfffff)
        run(driver, struct.pack('<4I', *values), 0, result, target, attr)
        cases += 1

    # The diagnostic reports only low 20 bits but compares all 32.
    high_only = list(PAYLOAD_WORDS)
    high_only[0] ^= 0x10000000
    run(driver, struct.pack('<4I', *high_only), 0,
        0x76000000 | (high_only[0] & 0xfffff), target, attr)
    cases += 1

    run(driver, PAYLOAD, 0xffff0007, 0x7fff0007, target, attr)
    cases += 1

    for scratch_result, scratch_value in ((0, 0), (0xffff0007, 0)):
        row = model.run_case(0xffff, RESULTS, 0, 0, driver_override=driver,
                             loaded_before=1, expected_result=0,
                             readbacks={POWER: (0, 0x800),
                                        SCRATCH: (scratch_result, scratch_value),
                                        RESET: (0, 0)},
                             extra_writes={**dict(video.EXPECTED_MAP), RESET: 0},
                             expected_smn_addresses=NORMAL_WRITES)
        if target == TMR:
            assert not any(event.get('stub') == 'map_buffer' and
                           event.get('address') == hex(TMR)
                           for event in row['events'])
        cases += 1

    row = model.run_case(0xffff, RESULTS, 0, 0, driver_override=driver,
                         loaded_before=1, expected_result=0,
                         readbacks={POWER: (0, 0x801)},
                         expected_smn_addresses=PREMAP_WRITES)
    assert [event['address'] for event in row['events']
            if event.get('stub_svc') == '0x7b'] == [hex(POWER)]
    if target == TMR:
        assert not any(event.get('stub') == 'map_buffer' and
                       event.get('address') == hex(TMR)
                       for event in row['events'])
    return cases + 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', required=True, type=Path)
    parser.add_argument('--control', action='store_true',
                        help='Probe the known-mapped PSP bookkeeping address')
    parser.add_argument('--read-attribute', action='store_true',
                        help='Check attribute -1 used by the signed driver read path')
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    if len(rom) != 0x1000000:
        raise ValueError('unexpected interposer view size')
    print(f'{check(rom[DRIVER:DRIVER + DRIVER_LEN], CONTROL if args.control else TMR,
                   0xffffffff if args.read_attribute else 0xfffffffe)} '
          f'PSP TMR-prefix read cases passed; '
          f'ROM SHA256 {hashlib.sha256(rom).hexdigest()}')


if __name__ == '__main__':
    main()
