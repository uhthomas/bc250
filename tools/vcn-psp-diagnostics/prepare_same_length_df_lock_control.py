#!/usr/bin/env python3
"""Make an OFFLINE, UNTESTED equal-length UEFI DF-lock control ROM.

Recompress the already-verified five-byte PE control with a longer LZMA
match search. The compressed stream then fits within the original FFS file;
the file and section headers remain byte-identical to the working ROM.
Unused bytes after the LZMA end marker fill the old file length. This is an
interposer research candidate, not a known VCN fix or BIOS flash image.
"""

import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path


WORKING_SHA256 = 'f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183'
CANDIDATE_SHA256 = 'f3bf69891739c5143748bc975dc7030e1144fdfebf27c325dccad5d748aa7c64'
FILE_START = 0xAE0078
STREAM_START = FILE_START + 48
NICE_LEN = 273
FFS_FIXED_CHECKSUM = 0xAA
FFS_ATTRIB_CHECKSUM = 0x40
GUIDED_PROCESSING_REQUIRED = 0x0001


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_size(image: bytes) -> int:
    return int.from_bytes(image[FILE_START + 20:FILE_START + 23], 'little')


def verify_outer_headers(image: bytes) -> None:
    ffs = image[FILE_START:FILE_START + 24]
    guided = image[FILE_START + 24:STREAM_START]
    if len(ffs) != 24 or len(guided) != 24:
        raise ValueError('truncated outer firmware headers')
    if ffs[19] & FFS_ATTRIB_CHECKSUM or ffs[17] != FFS_FIXED_CHECKSUM:
        raise ValueError('outer FFS file uses a data checksum')
    if (sum(ffs) - ffs[17] - ffs[23]) & 0xff:
        raise ValueError('outer FFS header checksum invalid')
    if guided[3] != 0x02 or int.from_bytes(guided[20:22], 'little') != 24 or (
            int.from_bytes(guided[22:24], 'little') != GUIDED_PROCESSING_REQUIRED):
        raise ValueError('unexpected LZMA guided-section header')


def build(working: bytes, candidate: bytes) -> tuple[bytes, dict]:
    if len(working) != 0x1000000 or digest(working) != WORKING_SHA256:
        raise ValueError('working ROM size or SHA256 mismatch')
    if len(candidate) != len(working) or digest(candidate) != CANDIDATE_SHA256:
        raise ValueError('existing control candidate size or SHA256 mismatch')
    verify_outer_headers(working)
    old_size, candidate_size = file_size(working), file_size(candidate)
    old_stream = working[STREAM_START:FILE_START + old_size]
    candidate_stream = candidate[STREAM_START:FILE_START + candidate_size]
    if old_stream[:5] != bytes.fromhex('5d00000001') or candidate_stream[:5] != old_stream[:5]:
        raise ValueError('unexpected LZMA properties')
    uncompressed = lzma.decompress(candidate_stream, format=lzma.FORMAT_ALONE)
    compressed = lzma.compress(
        uncompressed, format=lzma.FORMAT_ALONE,
        filters=[dict(id=lzma.FILTER_LZMA1, dict_size=0x1000000,
                      lc=3, lp=0, pb=2, nice_len=NICE_LEN)])
    compressed = compressed[:5] + len(uncompressed).to_bytes(8, 'little') + compressed[13:]
    if len(compressed) > len(old_stream):
        raise ValueError('control no longer fits the original FFS file')
    padding = len(old_stream) - len(compressed)
    replacement = compressed + b'\xff' * padding
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    decompressed = decoder.decompress(replacement)
    if len(replacement) != len(old_stream) or not decoder.eof or (
            decoder.unused_data != b'\xff' * padding or
            decompressed != uncompressed):
        raise ValueError('equal-length LZMA stream failed round-trip')
    image = bytearray(working)
    image[STREAM_START:FILE_START + old_size] = replacement
    image = bytes(image)
    verify_outer_headers(image)
    if image[:STREAM_START] != working[:STREAM_START] or (
            image[FILE_START + old_size:] != working[FILE_START + old_size:]):
        raise AssertionError('control changed bytes outside original compressed stream')
    first_diff = next(i for i, (a, b) in enumerate(zip(working, image)) if a != b)
    if first_diff < 0xAE1000:
        raise ValueError(f'compressed prefix changed unexpectedly early: {first_diff:#x}')
    report = dict(purpose='UNTESTED offline DF-lock omission; no chip write',
                  working_sha256=WORKING_SHA256,
                  prior_candidate_sha256=CANDIDATE_SHA256,
                  image_sha256=digest(image),
                  original_ffs_file_size=old_size,
                  new_ffs_file_size=file_size(image),
                  original_stream_size=len(old_stream),
                  compressed_stream_size=len(compressed),
                  trailing_padding_bytes=padding,
                  first_changed_spi_offset=f'{first_diff:06x}',
                  file_and_section_headers_unchanged=(
                      image[FILE_START:STREAM_START] == working[FILE_START:STREAM_START]),
                  decompressed_payload_matches_prior_candidate=True,
                  hardware_tested=False,
                  bios_flash_written=False,
                  pico_flash_written=False)
    return image, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--working-rom', required=True, type=Path)
    parser.add_argument('--candidate-rom', required=True, type=Path)
    parser.add_argument('--output-rom', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    if any('output' not in path.parts or path.exists()
           for path in (args.output_rom, args.report)):
        parser.error('outputs must be new private files under output/')
    image, report = build(args.working_rom.read_bytes(), args.candidate_rom.read_bytes())
    for path, payload in ((args.output_rom, image),
                          (args.report, (json.dumps(report, indent=2) + '\n').encode())):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(payload)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
