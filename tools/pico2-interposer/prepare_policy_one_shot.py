#!/usr/bin/env python3
"""Substitute one SEC_GASKET tuple read without changing the signed ROM.

The captured boot reads the policy value twice. This builds a RAM-only Pico
profile that substitutes one read and passes through the other, so the two
possible check/use orders can be tested separately. No flash image is made.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


ROM_SHA = "f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183"
BASE_PROFILES = {
    "58f61d531a41dcd5415c0a073a701945b26b0d2798fa8d26a2f4625cca94f943":
        ("abl0-entry-policy", "read-only 0x1f820 low16"),
    "52e76f9b87420249301d4cef65876d9743e3d3f14e982ac5edbf1edbdd7bedd8":
        ("abl0-entry-harvest", "read-only 0x1f81c low16"),
    "e7d22bc11417e647b2d5417e45c0c430323b5bbc53755d424240909c0e10ae44":
        ("abl0-entry-harvest", "read-only 0x1f81c low16, direct signature lookup"),
    "415ac9e2c82d7598f32bc8a86826288b0267b4f986061794fd1e188a754ef33a":
        ("abl0-entry-policy", "read-only 0x1f8a4 low16, direct signature lookup"),
    "904439cabdb2495cb49271f9d55928c0cdc0db980349023b135cfb58148a0818":
        ("abl0-entry-fabric", "read-only 0x50d6c low16"),
}
TARGETS = {
    "0x1f820": (0x0398306C, 0x185103, [2699, 5539]),
    "0x1f8a4": (0x03983064, 0xB, [2697, 5537]),
}


def checked(path: Path, digest: str) -> bytes:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"unexpected SHA256: {path}")
    return data


def replace_one(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"expected exactly one occurrence of {old!r}")
    return text.replace(old, new)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--base-profile", type=Path, required=True)
    parser.add_argument("--read", choices=("first", "second"), required=True)
    parser.add_argument("--target", choices=TARGETS, default="0x1f820")
    parser.add_argument("--set-1f8a4-f", action="store_true",
                        help="change the selected 0x1f8a4 value from 0xb to the Deck policy's 0xf")
    parser.add_argument("--also-zero-1f820", action="store_true",
                        help="also change the first read of the adjacent 0x1f820 policy value")
    parser.add_argument("--retarget-1f820-to-harvest", action="store_true",
                        help="first-read-only request 0x1f81c <- 0 instead of 0x1f820 <- 0x185103")
    parser.add_argument("--retarget-1f820-to-fabric", action="store_true",
                        help="first-read-only request 0x50d6c <- 0x8c0; ABL0 hook reads it back")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.also_zero_1f820 and (args.target != "0x1f8a4" or args.read != "first"):
        parser.error("the two-value trial requires the first 0x1f8a4 read")
    if args.set_1f8a4_f and (args.target != "0x1f8a4" or args.read != "first" or
                              args.also_zero_1f820 or args.retarget_1f820_to_harvest or
                              args.retarget_1f820_to_fabric):
        parser.error("the 0xf trial requires only the first 0x1f8a4 read")
    if args.retarget_1f820_to_harvest and (args.target != "0x1f820" or
                                            args.read != "first" or args.also_zero_1f820):
        parser.error("the harvest retarget requires only the first 0x1f820 read")
    if args.retarget_1f820_to_fabric and (args.target != "0x1f820" or
                                           args.read != "first" or args.also_zero_1f820 or
                                           args.retarget_1f820_to_harvest):
        parser.error("the fabric retarget requires only the first 0x1f820 read")
    command, original_value, expected_rows = TARGETS[args.target]

    rom = checked(args.rom, ROM_SHA)
    profile_bytes = args.base_profile.read_bytes()
    profile_sha = hashlib.sha256(profile_bytes).hexdigest()
    if profile_sha not in BASE_PROFILES:
        raise ValueError(f"unexpected base profile SHA256: {args.base_profile}")
    base_name, hook_description = BASE_PROFILES[profile_sha]
    if args.retarget_1f820_to_fabric and (
            (base_name, hook_description) not in (
                ("abl0-entry-fabric", "read-only 0x50d6c low16"),
                ("abl0-entry-policy", "read-only 0x1f820 low16"))):
        raise ValueError("fabric retarget requires the ABL0 fabric or original-policy readback")
    profile = profile_bytes.decode()
    if struct.unpack_from("<I", rom, command & 0xFFFFFF)[0] != original_value:
        raise ValueError("original SEC_GASKET tuple changed")
    if args.also_zero_1f820 and \
            struct.unpack_from("<I", rom, TARGETS["0x1f820"][0] & 0xFFFFFF)[0] != 0x185103:
        raise ValueError("adjacent SEC_GASKET tuple changed")
    if (args.retarget_1f820_to_harvest or args.retarget_1f820_to_fabric) and \
            struct.unpack_from("<I", rom, 0x983068)[0] != 0x1F820:
        raise ValueError("SEC_GASKET target address changed")
    if hashlib.sha256(rom[0x982100:0x984D50]).digest() != rom[0x9820D0:0x9820F0]:
        raise ValueError("stock SEC_GASKET digest mismatch")
    stock_key = rsa.RSAPublicNumbers(
        65537, int.from_bytes(rom[0x9DB530:0x9DB630], "little")).public_key()
    stock_key.verify(rom[0x984D50:0x984E50], rom[0x982000:0x984D50],
                     padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                     hashes.SHA256())

    run_text = profile.split("static const struct expected_run", 1)[1].split("};", 1)[0]
    runs = [(int(command, 16), int(count)) for command, count in
            re.findall(r"\{0x([0-9a-f]+)u, (\d+)u\}", run_text)]
    if len(runs) != 37 or sum(count for _, count in runs) != 872744:
        raise ValueError("captured SPI run geometry changed")
    rows = []
    row = 0
    for start, count in runs:
        if start <= command < start + 4 * count:
            rows.append(row + (command - start) // 4)
        row += count
    if rows != expected_rows:
        raise ValueError(f"unexpected SEC_GASKET read rows: {rows}")
    word_text = profile.split("static const struct patch_word", 1)[1].split("};", 1)[0]
    if f"0x{command:08x}u" in word_text or "0x039db530u" in word_text or \
            "0x03984d50u" in word_text:
        raise ValueError("base profile already changes early policy or usage-31 key")
    retarget = args.retarget_1f820_to_harvest or args.retarget_1f820_to_fabric
    second_command = (0x0398306C if args.also_zero_1f820 else
                      0x03983068 if retarget else None)
    if second_command is not None and f"0x{second_command:08x}u" in word_text:
        raise ValueError("base profile already changes the second policy word")
    chosen = rows[0 if args.read == "first" else 1]
    suffix = ("harvest" if base_name == "abl0-entry-harvest" else
              "fabric" if base_name == "abl0-entry-fabric" else "policy")
    target_suffix = "" if args.target == "0x1f820" else "-1f8a4"
    pair_suffix = "-and-1f820" if args.also_zero_1f820 else ""
    name = (f"policy-first-read-1f8a4-f-{suffix}"
            if args.set_1f8a4_f else
            f"policy-first-read-50d6c-bit11-{suffix}"
            if args.retarget_1f820_to_fabric else
            f"policy-first-read-1f81c-zero-{suffix}"
            if args.retarget_1f820_to_harvest else
            f"policy-{args.read}-read-zero{target_suffix}{pair_suffix}-{suffix}")
    profile = replace_one(profile, f'#define PROFILE_NAME "{base_name}"',
                          f'#define PROFILE_NAME "{name}"')
    profile = replace_one(profile, '#define PROFILE_EXPECTED_PATCH_READS 697u',
                          f'#define PROFILE_EXPECTED_PATCH_READS {699 if (args.also_zero_1f820 or retarget) else 698}u\n'
                          f'#define PROFILE_POLICY_ONE_SHOT_ROW {chosen}u\n'
                          f'#define PROFILE_POLICY_ONE_SHOT_COMMAND 0x{command:08x}u\n'
                          f'#define PROFILE_POLICY_ONE_SHOT_REPLY {"0x0f000000u" if args.set_1f8a4_f else "0xc0080000u" if args.retarget_1f820_to_fabric else "0u"}')
    if args.also_zero_1f820:
        profile = replace_one(profile, '#define PROFILE_POLICY_ONE_SHOT_REPLY 0u',
                              '#define PROFILE_POLICY_ONE_SHOT_REPLY 0u\n'
                              '#define PROFILE_POLICY_ONE_SHOT2_ROW 2699u\n'
                              '#define PROFILE_POLICY_ONE_SHOT2_COMMAND 0x0398306cu\n'
                              '#define PROFILE_POLICY_ONE_SHOT2_REPLY 0u')
    if args.retarget_1f820_to_harvest:
        profile = replace_one(profile, '#define PROFILE_POLICY_ONE_SHOT_REPLY 0u',
                              '#define PROFILE_POLICY_ONE_SHOT_REPLY 0u\n'
                              '#define PROFILE_POLICY_ONE_SHOT2_ROW 2698u\n'
                              '#define PROFILE_POLICY_ONE_SHOT2_COMMAND 0x03983068u\n'
                              '#define PROFILE_POLICY_ONE_SHOT2_REPLY 0x1cf80100u')
    if args.retarget_1f820_to_fabric:
        profile = replace_one(profile, '#define PROFILE_POLICY_ONE_SHOT_REPLY 0xc0080000u',
                              '#define PROFILE_POLICY_ONE_SHOT_REPLY 0xc0080000u\n'
                              '#define PROFILE_POLICY_ONE_SHOT2_ROW 2698u\n'
                              '#define PROFILE_POLICY_ONE_SHOT2_COMMAND 0x03983068u\n'
                              '#define PROFILE_POLICY_ONE_SHOT2_REPLY 0x6c0d0500u')

    args.output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    header = args.output_dir / "sparse_physical_profile.h"
    fd = os.open(header, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(profile.encode())
    summary = {
        "mode": "one-read-only-policy-tuple-substitution",
        "stock_rom_sha256": ROM_SHA,
        "base_profile_sha256": profile_sha,
        "profile_sha256": hashlib.sha256(profile.encode()).hexdigest(),
        "changed_read": args.read,
        "policy_address": args.target,
        "original_value": hex(original_value),
        "trial_value": "0xf" if args.set_1f8a4_f else
                       "0x8c0" if args.retarget_1f820_to_fabric else "0x0",
        "also_zero_0x1f820": args.also_zero_1f820,
        "retarget_to_0x1f81c": args.retarget_1f820_to_harvest,
        "retarget_to_0x50d6c": args.retarget_1f820_to_fabric,
        "changed_row": chosen,
        "other_row": rows[1 if args.read == "first" else 0],
        "policy_signature_and_key": "original",
        "policy_rom_bytes": "original",
        "abl0_hook": hook_description,
        "expected_patch_reads_per_pass": 699 if (args.also_zero_1f820 or retarget) else 698,
        "bios_flash_allowed": False,
        "hardware_decode_verified": False,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
