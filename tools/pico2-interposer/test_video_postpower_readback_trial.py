#!/usr/bin/env python3
"""Exercise the conditional post-power PSP readback hook offline."""

import argparse
import importlib.util
from pathlib import Path


POWER = 0x1f810
RESET = 0x0900c004


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', required=True, type=Path)
    parser.add_argument('--address', type=lambda value: int(value, 0), default=RESET)
    parser.add_argument('--write-cache', action='store_true')
    args = parser.parse_args()
    extra_write = (args.address, 0x1fa00000) if args.write_cache else None
    postpower_writes = ['0x900c004', '0x1f8a4'] + ([hex(args.address)] if extra_write else [])
    spec = importlib.util.spec_from_file_location(
        'bc250_postload_model', Path(__file__).with_name('postload_model.py'))
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    rom = args.rom.read_bytes()
    assert len(rom) == 0x1000000
    driver = rom[0x984f00:0x984f00 + 0x1a770]
    cases = 0

    for value in (0x801, 0x802, 0xffffffff):
        row = model.run_case(0xffff, 0, 0, 0, driver_override=driver,
                             expected_result=0,
                             readbacks={POWER: (0, value)}, extra_write=extra_write)
        assert row['loaded_flag'] == 1
        assert [e['address'] for e in row['events'] if e.get('stub_svc') == '0x7b'] == [hex(POWER)]
        cases += 1

    for value in (0, 1, 0xffffffff, 0xdeadbeef):
        diagnostic = 0x70000000 | (value & 0x0fffffff)
        row = model.run_case(0xffff, 0, 0, 0, driver_override=driver,
                             expected_result=diagnostic, loaded_before=1,
                             readbacks={POWER: (0, 0x800), args.address: (0, value)},
                             extra_write=extra_write, expected_smn_addresses=postpower_writes)
        assert row['loaded_flag'] == 1
        assert [e['address'] for e in row['events'] if e.get('stub_svc') == '0x7b'] == [hex(POWER), hex(args.address)]
        cases += 1

    for address, status, expected in ((POWER, 0xffff0007, 0),
                                      (args.address, 0xffff0008, 0xffff0008)):
        readbacks = {POWER: (0, 0x800), args.address: (0, 1)}
        readbacks[address] = (status, 0)
        row = model.run_case(0xffff, 0, 0, 0, driver_override=driver,
                             expected_result=expected, readbacks=readbacks,
                             extra_write=extra_write,
                             expected_smn_addresses=(postpower_writes if address != POWER
                                                     else ['0x900c004', '0x1f8a4']))
        assert row['loaded_flag'] == int(expected == 0)
        cases += 1

    for first, second in ((0xffff0001, 0), (0, 0xffff0002)):
        expected = first or second
        row = model.run_case(0xffff, {RESET: first, 0x1f8a4: second}, 0, 0,
                             driver_override=driver, expected_result=expected,
                             extra_write=extra_write,
                             expected_smn_addresses=([hex(RESET)] if first else
                                                     [hex(RESET), hex(0x1f8a4)]))
        assert not any(e.get('stub_svc') == '0x7b' for e in row['events'])
        cases += 1

    for context in (0, 7):
        row = model.run_case(context, 0, 0, 0, driver_override=driver)
        assert row['return'] == '0x0' and row['loaded_flag'] == 1
        assert not any(e.get('stub_svc') == '0x7b' for e in row['events'])
        cases += 1

    if extra_write:
        row = model.run_case(0xffff,
                             {RESET: 0, 0x1f8a4: 0, args.address: 0xffff0009},
                             0, 0, driver_override=driver,
                             expected_result=0xffff0009,
                             expected_smn_addresses=postpower_writes,
                             readbacks={POWER: (0, 0x800), args.address: (0, 0)},
                             extra_write=extra_write)
        assert [e['address'] for e in row['events'] if e.get('stub_svc') == '0x7b'] == [hex(POWER)]
        cases += 1

    print(f'{cases} native post-power PSP readback cases passed')


if __name__ == '__main__':
    main()
