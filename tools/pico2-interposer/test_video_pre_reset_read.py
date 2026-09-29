#!/usr/bin/env python3
"""Execute the early signed-driver reset-read hook against pinned PSP code."""

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
    parser.add_argument('--target', type=lambda value: int(value, 0), default=0x20180)
    parser.add_argument('--early', action='store_true',
                        help='Read on the first, unpowered VCN firmware request')
    parser.add_argument('--direct', action='store_true',
                        help='Read target without the powered-profile selector')
    args = parser.parse_args()
    if args.target < 0 or args.target > 0xffffc or args.target & 3:
        parser.error('--target must be an aligned PSP service word in 0..0xffffc')
    rom = args.rom.read_bytes()
    assert len(rom) == 0x1000000
    driver = rom[0x984f00:0x984f00 + 0x1a770]
    model = load_model()
    second_reset, power, read_target = 0x1f8a4, 0x1f810, args.target
    if args.direct:
        assert not args.early
        writes = {second_reset: 0}
        cases = 0
        for value in (0, 1, 2, 3, 0xf0, 0xffffffff):
            row = model.run_case(0xffff, writes, 0, 0, driver_override=driver,
                                 readbacks={read_target: (0, value)},
                                 expected_result=0x70000000 | (value & 0x0fffffff),
                                 expected_smn_addresses=[])
            assert [x['address'] for x in row['events']
                    if x.get('stub_svc') == '0x7b'] == [hex(read_target)]
            cases += 1
        row = model.run_case(0xffff, writes, 0, 0, driver_override=driver,
                             readbacks={read_target: (0xffff000a, 0)},
                             expected_result=0xffff000a,
                             expected_smn_addresses=[])
        assert [x['address'] for x in row['events']
                if x.get('stub_svc') == '0x7b'] == [hex(read_target)]
        cases += 1
        row = model.run_case(0, writes, 0, 0, driver_override=driver,
                             expected_result=0,
                             expected_smn_addresses=[hex(second_reset)])
        assert not [x for x in row['events'] if x.get('stub_svc') == '0x7b']
        cases += 1
        print(f'{cases} pinned PSP direct-read instruction cases passed')
        return
    selected_power = 0x801 if args.early else 0x800
    fallback_power = 0x800 if args.early else 0x801
    writes = {second_reset: 0}
    cases = 0

    row = model.run_case(0xffff, writes, 0, 0, driver_override=driver,
                         readbacks={power: (0, fallback_power)}, expected_result=0,
                         expected_smn_addresses=[hex(second_reset), hex(second_reset)])
    assert [x['address'] for x in row['events'] if x.get('stub_svc') == '0x7b'] == [hex(power)]
    assert row['loaded_flag'] == 1
    cases += 1

    for value in (0, 1, 0x200d, 0xffffffff):
        row = model.run_case(0xffff, writes, 0, 0, driver_override=driver,
                             loaded_before=0 if args.early else 1,
                             readbacks={power: (0, selected_power),
                                        read_target: (0, value)},
                             expected_result=0x70000000 | (value & 0x0fffffff),
                             expected_smn_addresses=[])
        assert [x['address'] for x in row['events'] if x.get('stub_svc') == '0x7b'] == [hex(power), hex(read_target)]
        assert row['loaded_flag'] == (0 if args.early else 1)
        cases += 1

    for readbacks, expected_reads in (
        ({power: (0xffff0009, 0)}, [power]),
        ({power: (0, selected_power), read_target: (0xffff000a, 0)},
         [power, read_target]),
    ):
        error = next(result for result, _ in readbacks.values() if result)
        row = model.run_case(0xffff, writes, 0, 0, driver_override=driver,
                             loaded_before=0 if args.early else 1,
                             readbacks=readbacks,
                             expected_result=error,
                             expected_smn_addresses=[])
        assert [x['address'] for x in row['events'] if x.get('stub_svc') == '0x7b'] == [hex(a) for a in expected_reads]
        cases += 1

    row = model.run_case(0, writes, 0, 0, driver_override=driver,
                         expected_result=0, expected_smn_addresses=[hex(second_reset)])
    assert not [x for x in row['events'] if x.get('stub_svc') == '0x7b']
    cases += 1
    print(f'{cases} pinned PSP instruction cases passed')


if __name__ == '__main__':
    main()
