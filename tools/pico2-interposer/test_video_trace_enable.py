#!/usr/bin/env python3
"""Execute the PSP-side VCPU trace-enable probe in the pinned driver model."""

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
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    assert len(rom) == 0x1000000
    driver = rom[0x984f00:0x984f00 + 0x1a770]
    model = load_model()
    power, vcpu, original = 0x1f810, 0x20160, 0x1f8a4

    row = model.run_case(0xffff, {original: 0}, 0, 0, driver_override=driver,
                         readbacks={power: (0, 0x801)}, expected_result=0,
                         expected_smn_addresses=[hex(original), hex(original)])
    assert [event['address'] for event in row['events']
            if event.get('stub_svc') == '0x7b'] == [hex(power)]
    cases = 1

    for before, after in ((0x0ff20200, 0x0ff20600),
                          (0x0ff20200, 0x0ff20200),
                          (0, 0x400)):
        row = model.run_case(0xffff, {original: 0, vcpu: 0}, 0, 0,
                             driver_override=driver, loaded_before=1,
                             readbacks={power: (0, 0x800),
                                        vcpu: [(0, before), (0, after)]},
                             extra_write=(vcpu, before | 0x400),
                             expected_result=0x70000000 | after,
                             expected_smn_addresses=[hex(vcpu)])
        assert [event['address'] for event in row['events']
                if event.get('stub_svc') == '0x7b'] == [hex(power), hex(vcpu), hex(vcpu)]
        cases += 1

    row = model.run_case(0xffff, {original: 0, vcpu: 0}, 0, 0,
                         driver_override=driver, loaded_before=1,
                         readbacks={power: (0, 0x800), vcpu: (0, 0x0ff20200)},
                         extra_write=(vcpu, 0x0ff20600),
                         extra_results={(vcpu, 0x0ff20600): 0xffff0009},
                         expected_result=0xffff0009,
                         expected_smn_addresses=[hex(vcpu)])
    assert [event['address'] for event in row['events']
            if event.get('stub_svc') == '0x7b'] == [hex(power), hex(vcpu)]
    cases += 1
    print(f'{cases} pinned PSP trace-enable instruction cases passed')


if __name__ == '__main__':
    main()
