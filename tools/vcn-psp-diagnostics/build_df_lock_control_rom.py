#!/usr/bin/env python3
"""Build an OFFLINE, UNTESTED DF-lock control ROM from the working BC250 dump.

The output is for structural verification only. Omitting the UEFI mailbox
command has not been tested on hardware and is not known to enable VCN.
"""

import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import struct

from prepare_df_lock_control import CALL_OFFSET, PE_SHA256, prepare
from prepare_df_lock_bootdone_control import EXIT_CALL_OFFSET, prepare as prepare_both


SOURCE_SHA256 = 'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183'
OUTER_FV = 0xae0000
OUTER_FILE = OUTER_FV + 0x78
INNER_FILE = 0xa7d80
INNER_PE = INNER_FILE + 0x58
EXPECTED_FILE_SHA256 = '9614e856d94118febe95e467e56f93b988065bf13767d469ba4c427f611285ef'
EXPECTED_FV_LEN = 4452352
ROM_LEN = 0x1000000


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_header_ok(header: bytes) -> bool:
    return len(header) == 24 and (sum(header) - header[17] - header[23]) & 255 == 0


def build(original: bytes, extracted_pe: bytes, extracted_inner_fv: bytes,
          also_omit_bootdone: bool = False):
    if len(original) != ROM_LEN or sha(original) != SOURCE_SHA256:
        raise ValueError('source is not pinned working control ROM')
    if sha(extracted_pe) != PE_SHA256 or len(extracted_inner_fv) != EXPECTED_FV_LEN:
        raise ValueError('extracted UEFI inputs are not pinned')
    outer_fv_len, = struct.unpack_from('<Q', original, OUTER_FV + 0x20)
    if not 0x160000 < outer_fv_len <= ROM_LEN - OUTER_FV:
        raise ValueError('unexpected outer FV size')
    old_file_size = int.from_bytes(original[OUTER_FILE + 20:OUTER_FILE + 23], 'little')
    old_file = original[OUTER_FILE:OUTER_FILE + old_file_size]
    if sha(old_file) != EXPECTED_FILE_SHA256 or not file_header_ok(old_file[:24]):
        raise ValueError('compressed FFS file differs or has invalid header')
    if old_file[18:20] != b'\x0b\x00' or old_file[23] != 0xf8:
        raise ValueError('unexpected FFS type, attributes or state')
    old_section_size = int.from_bytes(old_file[24:27], 'little')
    if old_file[27] != 2 or old_section_size + 24 != old_file_size:
        raise ValueError('unexpected GUID-defined section layout')
    guid_data = old_file[28:48]
    if guid_data[:16].hex() != '98584eee143959429d6edc7bd79403cf' or guid_data[16:20] != b'\x18\x00\x01\x00':
        raise ValueError('unexpected GUID-defined LZMA header')
    old_stream = old_file[48:]
    if old_stream[:5] != bytes.fromhex('5d00000001'):
        raise ValueError('unexpected LZMA properties')
    unpacked = lzma.decompress(old_stream, format=lzma.FORMAT_ALONE)
    if unpacked[:16] != bytes.fromhex('0c000019000000000000000004f04317'):
        raise ValueError('unexpected decompressed section wrapper')
    if unpacked[16:] != extracted_inner_fv:
        raise ValueError('extracted inner FV differs from working control ROM')
    fv = bytearray(unpacked[16:])
    if fv[INNER_FILE:INNER_FILE + 24] != extracted_inner_fv[INNER_FILE:INNER_FILE + 24]:
        raise ValueError('nested FFS header differs')
    if fv[INNER_FILE + 19] != 0 or not file_header_ok(fv[INNER_FILE:INNER_FILE + 24]):
        raise ValueError('nested FFS checksum mode or header unexpected')
    if fv[INNER_PE:INNER_PE + len(extracted_pe)] != extracted_pe:
        raise ValueError('target PE not at pinned nested FV offset')
    replacement_pe = prepare_both(extracted_pe) if also_omit_bootdone else prepare(extracted_pe)
    fv[INNER_PE:INNER_PE + len(extracted_pe)] = replacement_pe
    changed_unpacked = unpacked[:16] + fv
    if len(changed_unpacked) != len(unpacked):
        raise AssertionError('inner FV length changed')
    new_stream = lzma.compress(
        changed_unpacked,
        format=lzma.FORMAT_ALONE,
        filters=[dict(id=lzma.FILTER_LZMA1, dict_size=0x1000000, lc=3, lp=0, pb=2)],
    )
    new_stream = new_stream[:5] + len(changed_unpacked).to_bytes(8, 'little') + new_stream[13:]
    if lzma.decompress(new_stream, format=lzma.FORMAT_ALONE) != changed_unpacked:
        raise ValueError('recompressed section failed round-trip')
    section_size = 4 + len(guid_data) + len(new_stream)
    file_size = 24 + section_size
    if file_size >= 0x1000000:
        raise ValueError('FFS file exceeds 24-bit size')
    new_header = bytearray(old_file[:24])
    new_header[20:23] = file_size.to_bytes(3, 'little')
    new_header[16] = 0
    new_header[16] = (-sum(new_header) + new_header[17] + new_header[23]) & 255
    if not file_header_ok(new_header):
        raise AssertionError('new FFS header checksum invalid')
    new_file = bytes(new_header) + section_size.to_bytes(3, 'little') + old_file[27:28] + guid_data + new_stream
    assert len(new_file) == file_size
    if original[OUTER_FILE + old_file_size:OUTER_FV + outer_fv_len].strip(b'\xff'):
        raise ValueError('outer FV does not have expected erased free area')
    if OUTER_FILE + file_size > OUTER_FV + outer_fv_len:
        raise ValueError('new FFS file would overrun outer FV')
    image = bytearray(original)
    image[OUTER_FILE:OUTER_FILE + file_size] = new_file
    if file_size < old_file_size:
        image[OUTER_FILE + file_size:OUTER_FILE + old_file_size] = b'\xff' * (old_file_size - file_size)
    if lzma.decompress(image[OUTER_FILE + 48:OUTER_FILE + file_size], format=lzma.FORMAT_ALONE) != changed_unpacked:
        raise AssertionError('ROM-embedded LZMA stream failed round-trip')
    return bytes(image), {
        'purpose': 'UNTESTED OFFLINE mailbox control; NEVER flash without further review',
        'also_omit_bootdone': also_omit_bootdone,
        'source_sha256': SOURCE_SHA256,
        'image_sha256': sha(image),
        'pe_original_sha256': PE_SHA256,
        'pe_control_sha256': sha(replacement_pe),
        'outer_file_offset': hex(OUTER_FILE),
        'old_outer_file_length': old_file_size,
        'new_outer_file_length': file_size,
        'inner_pe_offset': hex(INNER_PE),
        'inner_pe_change_offset': hex(INNER_PE + CALL_OFFSET),
        'inner_pe_bootdone_change_offset': hex(INNER_PE + EXIT_CALL_OFFSET) if also_omit_bootdone else None,
        'new_ffs_header_checksum_valid': file_header_ok(new_header),
        'no_chip_write': True,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-rom', required=True, type=Path)
    ap.add_argument('--extracted-pe', required=True, type=Path)
    ap.add_argument('--extracted-inner-fv', required=True, type=Path)
    ap.add_argument('--output-rom', required=True, type=Path)
    ap.add_argument('--report', required=True, type=Path)
    ap.add_argument('--also-omit-bootdone', action='store_true',
                    help='also omit mailbox command 0x06; offline research control only')
    args = ap.parse_args()
    image, report = build(args.source_rom.read_bytes(), args.extracted_pe.read_bytes(),
                          args.extracted_inner_fv.read_bytes(), args.also_omit_bootdone)
    for path, payload in [(args.output_rom, image), (args.report, (json.dumps(report, indent=2) + '\n').encode())]:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
