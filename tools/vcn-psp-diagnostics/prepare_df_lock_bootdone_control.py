#!/usr/bin/env python3
"""Make an extracted-PE-only, UNTESTED two-command mailbox control.

This omits DF lock 0x1b and ExitBootServices/BOOT_DONE 0x06 as a research
control. It is not a bootable image and is not known to enable BC250 VCN.
"""

import argparse
import hashlib
import os
from pathlib import Path

from prepare_df_lock_control import PE_SHA256, REPLACEMENT, prepare as omit_df_lock


EXIT_CALL_OFFSET = 0x8c1
EXIT_CALL = bytes.fromhex('e862160000')  # call shared PSP mailbox helper 0x1f28
EXIT_CONTEXT = bytes.fromhex('ba06000000488bcfe862160000')


def prepare(original: bytes) -> bytes:
    if hashlib.sha256(original).hexdigest() != PE_SHA256:
        raise ValueError('AmdPspDxeV2 PE differs from pinned extraction')
    if original[EXIT_CALL_OFFSET-8:EXIT_CALL_OFFSET+5] != EXIT_CONTEXT:
        raise ValueError('ExitBootServices mailbox call context differs')
    if original.count(b'Psp.C2PMbox.ExitBootServices') != 1:
        raise ValueError('ExitBootServices diagnostic string absent or duplicated')
    changed = bytearray(omit_df_lock(original))
    if changed[EXIT_CALL_OFFSET:EXIT_CALL_OFFSET+5] != EXIT_CALL:
        raise ValueError('ExitBootServices call differs')
    changed[EXIT_CALL_OFFSET:EXIT_CALL_OFFSET+5] = REPLACEMENT
    return bytes(changed)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-pe', required=True, type=Path)
    ap.add_argument('--output-pe', required=True, type=Path)
    args = ap.parse_args()
    changed = prepare(args.input_pe.read_bytes())
    fd = os.open(args.output_pe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(changed)
    print(f'extracted two-command PE SHA256 {hashlib.sha256(changed).hexdigest()}')
    print('UNTESTED, not bootable; do not flash')


if __name__ == '__main__':
    main()
