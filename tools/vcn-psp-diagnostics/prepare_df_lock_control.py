#!/usr/bin/env python3
"""Make an extracted-PE-only control that omits BIOS DF-lock mailbox cmd 0x1b.

This is NOT a bootable ROM or a flash candidate. The enclosing compressed
firmware volume, checksums, SPI read coverage and live effects are unverified.
"""

import argparse
import hashlib
import os
from pathlib import Path


PE_SHA256 = '554e1b4bc50d38578b09d58cc2fcdb0f460ad3c164eab9009be706a551dc1c92'
CALL_OFFSET = 0x229f
ORIGINAL = bytes.fromhex('e884fcffff')  # call 0x1f28, edx == 0x1b
REPLACEMENT = bytes.fromhex('b801000000')  # mov eax, 1; match success path
CONTEXT = bytes.fromhex('ba1b000000488bcfc70710000000e884fcffff')


def prepare(original: bytes) -> bytes:
    if hashlib.sha256(original).hexdigest() != PE_SHA256:
        raise ValueError('AmdPspDxeV2 PE differs from pinned extraction')
    if original[CALL_OFFSET-14:CALL_OFFSET+5] != CONTEXT:
        raise ValueError('DF-lock call and argument context differ')
    for label in (b'PspMboxBiosLockDFReg_START', b'Psp.C2PMbox.LockDFReg',
                  b'PspMboxBiosLockDFReg_END'):
        if original.count(label) != 1:
            raise ValueError(f'missing or duplicated diagnostic string {label!r}')
    changed = bytearray(original)
    changed[CALL_OFFSET:CALL_OFFSET+len(ORIGINAL)] = REPLACEMENT
    if any(i < CALL_OFFSET or i >= CALL_OFFSET+len(ORIGINAL)
           for i, (a, b) in enumerate(zip(original, changed)) if a != b):
        raise ValueError('changed bytes outside DF-lock call')
    return bytes(changed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-pe', required=True, type=Path)
    parser.add_argument('--output-pe', required=True, type=Path)
    args = parser.parse_args()
    changed = prepare(args.input_pe.read_bytes())
    fd = os.open(args.output_pe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(changed)
    print(f'extracted PE control SHA256 {hashlib.sha256(changed).hexdigest()}')
    print('NOT a ROM; do not flash or load without full firmware-volume rebuild and verification')


if __name__ == '__main__':
    main()
