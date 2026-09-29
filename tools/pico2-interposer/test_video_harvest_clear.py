#!/usr/bin/env python3
"""Execute the guarded CC_UVD_HARVESTING write in the pinned PSP model."""

import argparse
import importlib.util
from pathlib import Path


def load_model():
    path = Path(__file__).with_name('postload_model.py')
    spec = importlib.util.spec_from_file_location('postload_model', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', required=True, type=Path)
    parser.add_argument('--early', action='store_true',
                        help='Clear on the first, unpowered VCN firmware request')
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    assert len(rom) == 0x1000000
    driver = rom[0x984f00:0x984f00 + 0x1a770]
    model = load_model()
    power, harvest, original = 0x1f810, 0x1f81c, 0x1f8a4
    selected_power = 0x801 if args.early else 0x800
    fallback_power = 0x800 if args.early else 0x801
    loaded_before = 0 if args.early else 1
    cases = 0

    row = model.run_case(0xffff, {original: 0}, 0, 0, driver_override=driver,
                         readbacks={power: (0, fallback_power)}, expected_result=0,
                         expected_smn_addresses=[hex(original), hex(original)])
    assert [event['address'] for event in row['events']
            if event.get('stub_svc') == '0x7b'] == [hex(power)]
    cases += 1

    for after in (0, 3):
        row = model.run_case(0xffff, {original: 0, harvest: 0}, 0, 0,
                             driver_override=driver, loaded_before=loaded_before,
                             readbacks={power: (0, selected_power),
                                        harvest: [(0, 3), (0, after)]},
                             extra_write=(harvest, 0),
                             expected_result=0x70000000 | after,
                             expected_smn_addresses=[hex(harvest)])
        assert [event['address'] for event in row['events']
                if event.get('stub_svc') == '0x7b'] == [hex(power), hex(harvest), hex(harvest)]
        cases += 1

    row = model.run_case(0xffff, {original: 0}, 0, 0, driver_override=driver,
                         loaded_before=loaded_before,
                         readbacks={power: (0, selected_power), harvest: (0, 1)},
                         expected_result=0x70000001,
                         expected_smn_addresses=[])
    assert [event['address'] for event in row['events']
            if event.get('stub_svc') == '0x7b'] == [hex(power), hex(harvest)]
    cases += 1

    row = model.run_case(0xffff, {original: 0, harvest: 0}, 0, 0,
                         driver_override=driver, loaded_before=loaded_before,
                         readbacks={power: (0, selected_power), harvest: (0, 3)},
                         extra_write=(harvest, 0),
                         extra_results={(harvest, 0): 0xffff0009},
                         expected_result=0xffff0009,
                         expected_smn_addresses=[hex(harvest)])
    assert [event['address'] for event in row['events']
            if event.get('stub_svc') == '0x7b'] == [hex(power), hex(harvest)]
    cases += 1
    print(f'{cases} pinned PSP harvest-clear instruction cases passed')


if __name__ == '__main__':
    main()
