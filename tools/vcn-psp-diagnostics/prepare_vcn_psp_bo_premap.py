#!/usr/bin/env python3
"""Add a delayed, read-only PSP check of the guarded ordinary-BO VCN map."""

import hashlib

import prepare_vcn_delayed_reset_read as delayed
import prepare_vcn_psp_bo_fetch as bo_fetch


SOURCE = bo_fetch.DEST / 'vcn_v2_0.c'
SOURCE_SHA = '3652327700e4c05132ad0f9ee2ceb3bc4a6f4991981f36d96ff58aedf75c9f1b'
DEST = bo_fetch.BUILD / 'vcn-psp-bo-premap-20260929'


def main() -> None:
    source = bo_fetch.read_pinned(SOURCE, SOURCE_SHA)
    if source.count(delayed.ANCHOR) != 1:
        raise ValueError('guarded VCPU wait anchor changed')
    probe = delayed.PROBE.replace(
        'reads reset before the signed driver\'s own control write.',
        'checks all sixteen ordinary-BO VCN cache windows before replay.')
    probe = probe.replace('BC250 VCN delayed reset:',
                          'BC250 VCN delayed BO map:')
    if probe == delayed.PROBE or 'BC250 VCN delayed reset:' in probe:
        raise AssertionError('delayed BO map diagnostic label did not change')
    candidate = source.replace(
        delayed.ANCHOR,
        delayed.ANCHOR[:-len('\t\tr = 0;\n')] + probe, 1)
    if candidate.count('psp_execute_ip_fw_load(&adev->psp, ucode)') != 2:
        raise AssertionError('unexpected powered PSP request count')
    DEST.mkdir(parents=True, exist_ok=True)
    for name, content in (
            ('amdgpu_vcn.c', bo_fetch.read_pinned(
                bo_fetch.DEST / 'amdgpu_vcn.c',
                '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8')),
            ('vcn_v2_0.c', candidate)):
        path = DEST / name
        if path.exists() and path.read_text() != content:
            raise ValueError(f'existing candidate differs: {path}')
        if not path.exists():
            path.write_text(content)
        print(name, hashlib.sha256(content.encode()).hexdigest())


if __name__ == '__main__':
    main()
