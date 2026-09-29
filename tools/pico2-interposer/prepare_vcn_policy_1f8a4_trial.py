#!/usr/bin/env python3
"""Add one early SEC_GASKET 0x1f8a4 read substitution to a pinned VCN image.

The signed late PSP VCN image is unchanged. This produces a RAM-only Pico
profile, not an image suitable for flashing either SPI device.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


BASE_PROFILE_SHA = "6c2c16431c3264bfba2b9a93c344b9bc1eb292fcddb12c45b3cc73fc403be7ba"
BASE_ROM_SHA = "4bb2a45d14dc12200d1f8b9d8a5a4725f98bb5b14e6dd099fe32beb9c8aaa323"
COMMAND = 0x03983064
FIRST_ROW = 2697
SECOND_ROW = 5537


def pinned(path: Path, digest: str) -> bytes:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"pinned input changed: {path}")
    return data


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"expected one {old!r}")
    return source.replace(old, new)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-profile", required=True, type=Path)
    parser.add_argument("--base-rom", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    profile = pinned(args.base_profile, BASE_PROFILE_SHA).decode()
    rom = pinned(args.base_rom, BASE_ROM_SHA)
    if struct.unpack_from("<I", rom, COMMAND & 0xffffff)[0] != 0xb:
        raise ValueError("the SEC_GASKET policy tuple is not 0xb")
    if hashlib.sha256(rom[0x982100:0x984d50]).digest() != rom[0x9820d0:0x9820f0]:
        raise ValueError("SEC_GASKET digest failed")
    key = rsa.RSAPublicNumbers(
        65537, int.from_bytes(rom[0x9db530:0x9db630], "little")
    ).public_key()
    key.verify(rom[0x984d50:0x984e50], rom[0x982000:0x984d50],
               padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
               hashes.SHA256())

    run_text = profile.split("static const struct expected_run", 1)[1].split("};", 1)[0]
    runs = [(int(address, 16), int(count)) for address, count in
            re.findall(r"\{0x([0-9a-f]+)u, (\d+)u\}", run_text)]
    rows = []
    cursor = 0
    for first, count in runs:
        if first <= COMMAND < first + 4 * count:
            rows.append(cursor + (COMMAND - first) // 4)
        cursor += count
    if len(runs) != 39 or cursor != 873480 or rows != [FIRST_ROW, SECOND_ROW]:
        raise ValueError(f"captured SPI geometry changed: {len(runs)}, {cursor}, {rows}")
    patches = profile.split("static const struct patch_word", 1)[1].split("};", 1)[0]
    if f"0x{COMMAND:08x}u" in patches:
        raise ValueError("base image already changes the target tuple")
    profile = replace_once(profile, '#define PROFILE_NAME "vcn-psp-bo-fetch"',
                           '#define PROFILE_NAME "vcn-bo-fetch-early-1f8a4-f"')
    profile = replace_once(profile, '#define PROFILE_EXPECTED_PATCH_READS 929u',
                           '#define PROFILE_EXPECTED_PATCH_READS 930u\n'
                           '#define PROFILE_POLICY_ONE_SHOT_ROW 2697u\n'
                           '#define PROFILE_POLICY_ONE_SHOT_COMMAND 0x03983064u\n'
                           '#define PROFILE_POLICY_ONE_SHOT_REPLY 0x0f000000u')

    args.output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    target = args.output_dir / "sparse_physical_profile.h"
    target.write_text(profile)
    target.chmod(0o600)
    summary = {
        "purpose": "test early 0x1f8a4=0xf with unchanged signed late VCN image",
        "base_rom_sha256": BASE_ROM_SHA,
        "base_profile_sha256": BASE_PROFILE_SHA,
        "profile_sha256": hashlib.sha256(profile.encode()).hexdigest(),
        "changed_spi_row": FIRST_ROW,
        "unchanged_second_spi_row": SECOND_ROW,
        "expected_patch_reads_per_pass": 930,
        "bios_flash_allowed": False,
        "pico_qspi_write_allowed": False,
        "hardware_decode_verified": False,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
