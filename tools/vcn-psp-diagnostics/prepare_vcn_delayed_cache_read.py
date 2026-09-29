#!/usr/bin/env python3
"""Generate the delayed cache-size0 diagnostic from the pinned VCN source."""

import hashlib

import prepare_vcn_delayed_reset_read as reset


DEST = reset.BUILD / 'vcn-delayed-cache-size0-20260929/vcn_v2_0.c'


def main() -> None:
    data = reset.SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != reset.SOURCE_SHA:
        raise ValueError('pinned VCN source changed')
    source = data.decode()
    if source.count(reset.ANCHOR) != 1:
        raise ValueError('VCPU wait anchor changed')
    probe = reset.PROBE.replace(
        'reads reset before the signed driver\'s own control write.',
        'reads cache-size0 without a reset write on the marked call.')
    probe = probe.replace('BC250 VCN delayed reset:',
                          'BC250 VCN delayed cache-size0:')
    if probe == reset.PROBE or 'BC250 VCN delayed reset:' in probe:
        raise AssertionError('cache diagnostic label did not change')
    candidate = source.replace(reset.ANCHOR,
                               reset.ANCHOR[:-len('\t\tr = 0;\n')] + probe, 1)
    if candidate.count('psp_execute_ip_fw_load(&adev->psp, ucode)') != 2:
        raise AssertionError('unexpected PSP request count')
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(candidate)
    print(DEST)
    print(hashlib.sha256(candidate.encode()).hexdigest())


if __name__ == '__main__':
    main()
