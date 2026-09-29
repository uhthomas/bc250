#!/usr/bin/env python3
"""Switch between pinned VCN Pico SRAM profiles on a diagnostic boot.

Stage one more diagnostic boot and arm Pi PDU recovery before resetting the
Pico. Pico loading uses picotool RAM only; neither SPI flash is written.
"""

import argparse
import sys

import iterate_diagnostic as batch


PROFILES = {
    'active': (batch.ACTIVE_UF2, batch.ACTIVE_SHA, 'vcn-psp-bo-fetch'),
    'premap': ('/home/pi/bc250-vcn-psp-bo-premap-20260929/bc250_psp_bo_premap.uf2',
               'b9a9768bbaacc4f7957f964cec52ed3640c31ce6af12ec2c99e98dff393502a2',
               'vcn-delayed-map-windows-premap-bo-fetch'),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=tuple(PROFILES))
    args = parser.parse_args()
    before = batch.state()
    batch.require_clean_boot(before, 'diagnostic')
    current_status = batch.pico_status()
    current = 'premap' if 'profile=vcn-delayed-map-windows-premap-bo-fetch ' \
        in current_status else 'active'
    batch.require_pico(current_status, current)
    if args.profile == current:
        print(f'{args.profile} is already armed; no cold cycle needed.',
              flush=True)
        return 0
    batch.pdu_status()
    uf2, expected_sha, profile_name = PROFILES[args.profile]
    batch.pin_uf2(uf2, expected_sha)
    batch.stage()
    timer = batch.arm_timer()
    result = batch.remote(batch.PI, ['python3', '/home/pi/load_and_arm_ram.py',
                                     '--uf2', uf2, '--profile', profile_name,
                                     '--picotool', batch.PICOTOOL], timeout=30)
    print(result.stdout.strip(), flush=True)
    batch.require_pico(batch.pico_status(), args.profile)
    after = batch.cycle(before['boot_id'], 'diagnostic', timer)
    batch.require_pico(batch.pico_status(), args.profile)
    print(f'{args.profile} armed after diagnostic boot {after["boot_id"]}.',
          flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
