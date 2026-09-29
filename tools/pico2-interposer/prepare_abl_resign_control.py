#!/usr/bin/env python3
"""Prepare an ABL signing-path interposer control; never flash its ROM.

By default every ABL payload is unchanged. A hook places code in unused
signed-header space and branches to it from the decompressed ABL body. The
harvest hook reads VCN harvesting; the fabric hook reads the data-fabric gate;
the guarded clear hook also tries one volatile write if the original value is
exactly 3. ABL3 may instead be hooked at its exit stub to distinguish a write
inside its worker from one between ABL stages. All five ABLs use usage-42.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


ROM_SHA = "f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183"
PROFILE_SHA = "f1a0c46b57e052f7943f7ab95e678fc3338ca16beaa21f6cabada54b489d7851"
ABL_STARTS = (0x99F700, 0x99FC00, 0x9ABB00, 0x9AFB00, 0x9B9D00)
ABL_BODY_SIZES = (0x240, 0xBCD0, 0x3D70, 0x9F60, 0x9DE0)
ABL_ENTRY_DIAG_ROWS = (139072, 165424, 173424, 226848, 247184)
EXPECTED_SIGNATURE_RANGES = (
    (0x99FA40, 0x99FB40),
    (0x9AB9D0, 0x9ABAD0),
    (0x9AF970, 0x9AFA70),
    (0x9B9B60, 0x9B9C60),
    (0x9C3BE0, 0x9C3CE0),
)
EXPECTED_SIGNATURE_READS = (64, 72, 72, 64, 64)
KEYDB_USAGE42_RECORD = 0x9DB240
KEYDB_USAGE42_MODULUS = KEYDB_USAGE42_RECORD + 0x50
KEYDB_USAGE31_RECORD = 0x9DB4E0
KEYDB_USAGE31_MODULUS = KEYDB_USAGE31_RECORD + 0x50
KEYDB_SECOND_COPY_ROW = 696
POLICY_START = 0x982000
POLICY_BODY_SIZE = 0x2C50
POLICY_VALUE = 0x98306C
POLICY_SIG_START = POLICY_START + 0x100 + POLICY_BODY_SIZE
POLICY_SIG_END = POLICY_SIG_START + 0x100
PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    if sha(data) != expected:
        raise ValueError(f"{path}: unexpected SHA256")
    return data


def private_write(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--abl0-entry-marker-binary", type=Path,
                        help="36-byte ARM hook linked at PSP address 0x54070")
    parser.add_argument("--abl0-entry-harvest-binary", type=Path,
                        help="96-byte ARM hook linked across ABL0 header's two empty regions")
    parser.add_argument("--abl0-entry-policy-binary", type=Path,
                        help="96-byte read-only ABL0-entry 0x1f820 policy hook")
    parser.add_argument("--abl0-entry-harvest-clear-binary", type=Path,
                        help="96-byte guarded volatile-write hook across the same regions")
    parser.add_argument("--abl0-entry-fabric-binary", type=Path,
                        help="96-byte read-only fabric-gate hook across the same regions")
    parser.add_argument("--abl-exit-fabric-toggle-binary", type=Path,
                        help="144-byte guarded ABL3-exit fabric write/restore probe")
    parser.add_argument("--abl-entry-fabric-toggle-binary", type=Path,
                        help="144-byte guarded ABL3-entry fabric write/restore probe")
    parser.add_argument("--abl-entry-noop-binary", type=Path,
                        help="36-byte no-op entry detour for ABL1..4")
    parser.add_argument("--abl-index", type=int, choices=range(5), default=0,
                        help="which ABL to hook; indexes 1..4 require the fabric probe")
    parser.add_argument("--abl-hook-site", choices=("entry", "exit"), default="entry",
                        help="branch from ABL entry or the ABL3 ARM exit stub")
    parser.add_argument("--sec-gasket-value", type=lambda value: int(value, 0),
                        choices=(0, 0x185103),
                        help="re-sign early SEC_GASKET with its 0x1f820 value unchanged or zero")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if sum(bool(path) for path in (args.abl0_entry_marker_binary,
                                    args.abl0_entry_harvest_binary,
                                    args.abl0_entry_policy_binary,
                                    args.abl0_entry_harvest_clear_binary,
                                    args.abl0_entry_fabric_binary,
                                    args.abl_exit_fabric_toggle_binary,
                                    args.abl_entry_fabric_toggle_binary,
                                    args.abl_entry_noop_binary)) > 1:
        parser.error("choose only one ABL hook")
    if args.abl_index and not (args.abl0_entry_fabric_binary or
                               args.abl_exit_fabric_toggle_binary or
                               args.abl_entry_fabric_toggle_binary or
                               args.abl_entry_noop_binary):
        parser.error("ABL1..4 require a fabric probe or no-op hook")
    if not args.abl_index and args.abl_entry_noop_binary:
        parser.error("the no-op detour is only for ABL1..4")
    if args.abl_hook_site == "exit" and \
            (args.abl_index != 3 or not (args.abl0_entry_fabric_binary or
                                          args.abl_exit_fabric_toggle_binary)):
        parser.error("the exit probe requires ABL3 and a fabric hook")
    if args.abl_exit_fabric_toggle_binary and args.abl_hook_site != "exit":
        parser.error("the fabric toggle is only supported at ABL3 exit")
    if args.abl_entry_fabric_toggle_binary and \
            (args.abl_index != 3 or args.abl_hook_site != "entry"):
        parser.error("the entry fabric toggle requires ABL3 entry")

    clean = checked(args.rom, ROM_SHA)
    if len(clean) != 0x1000000:
        raise ValueError("expected 16 MiB ROM")
    source = checked(args.profile, PROFILE_SHA).decode()
    marker = "static const struct expected_run expected_runs[PROFILE_RUNS] = {"
    run_block = source.split(marker, 1)[1].split("};", 1)[0]
    runs = [(int(address, 16), int(count)) for address, count in
            re.findall(r"\{0x([0-9a-f]+)u, (\d+)u\}", run_block)]
    if len(runs) != 37 or sum(count for _, count in runs) != 872744:
        raise ValueError("captured SPI profile geometry changed")

    if struct.unpack_from("<I", clean, KEYDB_USAGE42_RECORD)[0] != 0x150 or \
            struct.unpack_from("<I", clean, KEYDB_USAGE42_RECORD + 8)[0] != 42:
        raise ValueError("usage-42 key record moved")
    if struct.unpack_from("<I", clean, KEYDB_USAGE31_RECORD)[0] != 0x150 or \
            struct.unpack_from("<I", clean, KEYDB_USAGE31_RECORD + 8)[0] != 31:
        raise ValueError("usage-31 key record moved")
    key = serialization.load_pem_private_key(args.private_key.read_bytes(), None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size != 2048:
        raise ValueError("expected RSA-2048 private key")
    modified = bytearray(clean)
    modified[KEYDB_USAGE42_MODULUS:KEYDB_USAGE42_MODULUS + 256] = (
        key.public_key().public_numbers().n.to_bytes(256, "little"))
    if args.sec_gasket_value is not None:
        if clean[POLICY_START + 0x10:POLICY_START + 0x14] != b"$PS1" or \
                struct.unpack_from("<I", clean, POLICY_START + 0x14)[0] != POLICY_BODY_SIZE or \
                clean[POLICY_VALUE - 4:POLICY_VALUE + 4] != bytes.fromhex("20f8010003511800") or \
                clean[POLICY_START + 0x38:POLICY_START + 0x48] != \
                clean[KEYDB_USAGE31_RECORD + 0x10:KEYDB_USAGE31_RECORD + 0x20] or \
                hashlib.sha256(clean[POLICY_START + 0x100:POLICY_SIG_START]).digest() != \
                clean[POLICY_START + 0xD0:POLICY_START + 0xF0]:
            raise ValueError("early SEC_GASKET image differs from pinned control")
        stock_key = rsa.RSAPublicNumbers(
            65537, int.from_bytes(clean[KEYDB_USAGE31_MODULUS:KEYDB_USAGE31_MODULUS + 256],
                                  "little")).public_key()
        stock_key.verify(clean[POLICY_SIG_START:POLICY_SIG_END],
                         clean[POLICY_START:POLICY_SIG_START], PSS, hashes.SHA256())
        modified[KEYDB_USAGE31_MODULUS:KEYDB_USAGE31_MODULUS + 256] = (
            key.public_key().public_numbers().n.to_bytes(256, "little"))
        modified[POLICY_VALUE:POLICY_VALUE + 4] = struct.pack("<I", args.sec_gasket_value)
        modified[POLICY_START + 0xD0:POLICY_START + 0xF0] = hashlib.sha256(
            modified[POLICY_START + 0x100:POLICY_SIG_START]).digest()
        policy_body = bytes(modified[POLICY_START:POLICY_SIG_START])
        policy_signature = key.sign(policy_body, PSS, hashes.SHA256())
        key.public_key().verify(policy_signature, policy_body, PSS, hashes.SHA256())
        modified[POLICY_SIG_START:POLICY_SIG_END] = policy_signature
    hook_kind = ("marker" if args.abl0_entry_marker_binary else
                 "harvest" if args.abl0_entry_harvest_binary else
                 "policy" if args.abl0_entry_policy_binary else
                 "harvest-clear" if args.abl0_entry_harvest_clear_binary else
                 "fabric" if args.abl0_entry_fabric_binary else
                 "fabric-toggle" if args.abl_exit_fabric_toggle_binary else
                 "fabric-toggle-entry" if args.abl_entry_fabric_toggle_binary else
                 "noop" if args.abl_entry_noop_binary else None)
    hook = None
    target = ABL_STARTS[args.abl_index]
    if hook_kind:
        hook = (args.abl0_entry_marker_binary or
                args.abl0_entry_harvest_binary or
                args.abl0_entry_policy_binary or
                args.abl0_entry_harvest_clear_binary or
                args.abl0_entry_fabric_binary or
                args.abl_exit_fabric_toggle_binary or
                args.abl_entry_fabric_toggle_binary or
                args.abl_entry_noop_binary).read_bytes()
        if hook_kind in ("marker", "noop"):
            if len(hook) != 36 or clean[target + 0x70:target + 0x94] != bytes(36):
                raise ValueError("ABL entry hook does not fit the pinned header")
            modified[target + 0x70:target + 0x94] = hook
        elif hook_kind in ("fabric-toggle", "fabric-toggle-entry"):
            if len(hook) != 144 or hook[48:52] != bytes(4) or \
                    hook[96:128] != bytes(32) or \
                    clean[target + 0x70:target + 0xA0] != bytes(48) or \
                    clean[target + 0xA4:target + 0xD0] != bytes(44) or \
                    clean[target + 0xF0:target + 0x100] != bytes(16):
                raise ValueError("ABL3 exit toggle does not fit pinned header caves")
            modified[target + 0x70:target + 0xA0] = hook[:48]
            modified[target + 0xA4:target + 0xD0] = hook[52:96]
            modified[target + 0xF0:target + 0x100] = hook[128:144]
        else:
            if len(hook) != 96 or hook[48:52] != bytes(4) or \
                    clean[target + 0x70:target + 0xA0] != bytes(48) or \
                    clean[target + 0xA4:target + 0xD0] != bytes(44):
                raise ValueError("ABL entry hook does not fit the two pinned header regions")
            modified[target + 0x70:target + 0xA0] = hook[:48]
            modified[target + 0xA4:target + 0xD0] = hook[52:]
        body_size = struct.unpack_from("<I", clean, target + 0x14)[0]
        original_compressed_size = struct.unpack_from("<I", clean, target + 0x54)[0]
        original = zlib.decompress(clean[target + 0x100:target + 0x100 + original_compressed_size])
        expected_entry = bytes.fromhex("18d09fe5" if args.abl_index == 0 else "10402de9")
        if body_size != ABL_BODY_SIZES[args.abl_index] or original[:4] != expected_entry:
            raise ValueError(f"ABL{args.abl_index} ARM entry or compressed-body geometry changed")
        body = bytearray(original)
        patch_offset = 0x0C if args.abl_hook_site == "exit" else 0
        if args.abl_hook_site == "exit" and original[patch_offset:patch_offset + 4] != \
                bytes.fromhex("1080bde8"):
            raise ValueError("ABL3 exit stub is not the pinned pop {r4,pc}")
        displacement = 0x54070 - (0x54100 + patch_offset + 8)
        if displacement % 4:
            raise ValueError("misaligned ABL entry branch")
        body[patch_offset:patch_offset + 4] = struct.pack(
            "<I", 0xEA000000 | ((displacement // 4) & 0xFFFFFF))
        compressed = zlib.compress(body, 9)
        if len(compressed) > body_size:
            raise ValueError(f"ABL{args.abl_index} entry hook exceeds the original signed body")
        modified[target + 0x54:target + 0x58] = struct.pack("<I", len(compressed))
        modified[target + 0xD0:target + 0xF0] = hashlib.sha256(body).digest()
        modified[target + 0x100:target + 0x100 + len(compressed)] = compressed
    abl_images = []
    for index, (abl, (expected_start, expected_end)) in enumerate(
            zip(ABL_STARTS, EXPECTED_SIGNATURE_RANGES)):
        if clean[abl + 0x10:abl + 0x14] != b"$PS1":
            raise ValueError(f"ABL{index} header changed")
        body_size = struct.unpack_from("<I", clean, abl + 0x14)[0]
        decompressed_size = struct.unpack_from("<I", clean, abl + 0x50)[0]
        compressed_size = struct.unpack_from("<I", modified, abl + 0x54)[0]
        sig_start = abl + 0x100 + body_size
        sig_end = sig_start + 0x100
        if (sig_start, sig_end) != (expected_start, expected_end) or \
                not compressed_size <= body_size:
            raise ValueError(f"ABL{index} geometry changed")
        decompressed = zlib.decompress(modified[abl + 0x100:abl + 0x100 + compressed_size])
        if len(decompressed) != decompressed_size or \
                hashlib.sha256(decompressed).digest() != modified[abl + 0xD0:abl + 0xF0]:
            raise ValueError(f"ABL{index} compressed body does not match its digest")
        signed_body = bytes(modified[abl:sig_start])
        signature = key.sign(signed_body, PSS, hashes.SHA256())
        key.public_key().verify(signature, signed_body, PSS, hashes.SHA256())
        modified[sig_start:sig_end] = signature
        if (index != args.abl_index or not hook) and bytes(modified[abl:sig_start]) != clean[abl:sig_start]:
            raise ValueError(f"ABL{index} signed body changed")
        abl_images.append({"name": f"ABL{index}", "signed_body_sha256": sha(signed_body),
                           "decompressed_sha256": sha(decompressed),
                           "signature_range": [hex(sig_start), hex(sig_end)],
                           "payload_unchanged": index != args.abl_index or not bool(hook)})
    allowed = lambda offset: (
        KEYDB_USAGE42_MODULUS <= offset < KEYDB_USAGE42_MODULUS + 256 or
        (args.sec_gasket_value is not None and
         (KEYDB_USAGE31_MODULUS <= offset < KEYDB_USAGE31_MODULUS + 256 or
          POLICY_VALUE <= offset < POLICY_VALUE + 4 or
          POLICY_START + 0xD0 <= offset < POLICY_START + 0xF0 or
          POLICY_SIG_START <= offset < POLICY_SIG_END)) or
        any(start <= offset < end for start, end in EXPECTED_SIGNATURE_RANGES) or
        (hook is not None and target <= offset < target + 0x100 + ABL_BODY_SIZES[args.abl_index] and
         (target + 0x54 <= offset < target + 0x58 or
          target + 0x70 <= offset < target + (0x94 if hook_kind in ("marker", "noop") else 0xA0) or
          (hook_kind in ("harvest", "policy", "harvest-clear", "fabric") and
           target + 0xA4 <= offset < target + 0xD0) or
          (hook_kind in ("fabric-toggle", "fabric-toggle-entry") and
           (target + 0xA4 <= offset < target + 0xD0 or
            target + 0xF0 <= offset < target + 0x100)) or
          target + 0xD0 <= offset < target + 0xF0 or
          target + 0x100 <= offset < target + 0x100 + ABL_BODY_SIZES[args.abl_index])))
    if any(a != b and not allowed(offset) for offset, (a, b) in
           enumerate(zip(clean, modified))):
        raise ValueError("re-sign-only control changed another ROM byte")
    changed = [(0x03000000 | address, int.from_bytes(modified[address:address + 4], "big"))
               for address in range(0, len(clean), 4)
               if clean[address:address + 4] != modified[address:address + 4]]
    key_first_index = next(index for index, (command, _) in enumerate(changed)
                           if command == 0x03000000 | KEYDB_USAGE42_MODULUS)
    if [command for command, _ in changed[key_first_index:key_first_index + 64]] != [
            0x03000000 | (KEYDB_USAGE42_MODULUS + offset) for offset in range(0, 256, 4)]:
        raise ValueError("usage-42 modulus patch words are not contiguous")
    if args.sec_gasket_value is not None:
        key31_first_index = next(index for index, (command, _) in enumerate(changed)
                                 if command == 0x03000000 | KEYDB_USAGE31_MODULUS)
        policy_sig_first_index = next(index for index, (command, _) in enumerate(changed)
                                      if command == 0x03000000 | POLICY_SIG_START)
        for base, first in ((KEYDB_USAGE31_MODULUS, key31_first_index),
                            (POLICY_SIG_START, policy_sig_first_index)):
            if [command for command, _ in changed[first:first + 64]] != [
                    0x03000000 | address for address in range(base, base + 256, 4)]:
                raise ValueError("early policy key/signature patch words are not contiguous")
    signature_first_indices = []
    for sig_start, sig_end in EXPECTED_SIGNATURE_RANGES:
        first = next(index for index, (command, _) in enumerate(changed)
                     if command == 0x03000000 | sig_start)
        if [command for command, _ in changed[first:first + 64]] != [
                0x03000000 | address for address in range(sig_start, sig_end, 4)]:
            raise ValueError("an ABL signature patch is not 64 contiguous words")
        signature_first_indices.append(first)
    changes = {command for command, _ in changed}
    covered_changes = set()
    rows = []
    row = 0
    key_patch_reads = 0
    key31_patch_reads = 0
    policy_signature_patch_reads = 0
    signature_patch_reads = [0] * len(ABL_STARTS)
    for start, count in runs:
        for index in range(count):
            command = start + 4 * index
            address = command & 0xFFFFFF
            if command in changes and not (
                    0x9DAD00 <= address < 0x9DBAD0 and row >= KEYDB_SECOND_COPY_ROW):
                rows.append(row)
                covered_changes.add(command)
                if KEYDB_USAGE42_MODULUS <= address < KEYDB_USAGE42_MODULUS + 256:
                    key_patch_reads += 1
                if KEYDB_USAGE31_MODULUS <= address < KEYDB_USAGE31_MODULUS + 256:
                    key31_patch_reads += 1
                if POLICY_SIG_START <= address < POLICY_SIG_END:
                    policy_signature_patch_reads += 1
                for image, (sig_start, sig_end) in enumerate(EXPECTED_SIGNATURE_RANGES):
                    if sig_start <= address < sig_end:
                        signature_patch_reads[image] += 1
            row += 1
    if key_patch_reads != 64 or tuple(signature_patch_reads) != EXPECTED_SIGNATURE_READS:
        raise ValueError("required key/signature reads are not all covered")
    if args.sec_gasket_value is not None and \
            (key31_patch_reads != 64 or policy_signature_patch_reads != 72):
        raise ValueError("early policy key/signature reads are not all covered")
    if covered_changes != changes:
        raise ValueError("some changed ROM words are outside the captured SPI profile")
    base_changes = 64 * (8 if args.sec_gasket_value is not None else 6)
    base_reads = 64 + sum(EXPECTED_SIGNATURE_READS) + \
        (136 if args.sec_gasket_value is not None else 0)
    if (not hook and args.sec_gasket_value in (None, 0x185103) and
            (len(changed), len(rows)) != (base_changes, base_reads)) or \
            (hook and (len(changed) <= base_changes or len(rows) <= base_reads)):
        raise ValueError("unexpected patch coverage")
    body_lookup = []
    if hook:
        by_address = {command & 0xffffff: index + 1
                      for index, (command, _) in enumerate(changed)}
        body_start = target
        body_end = target + 0x100 + ABL_BODY_SIZES[args.abl_index]
        body_lookup = [by_address.get(address, 0)
                       for address in range(body_start, body_end, 4)]
        if max(body_lookup) > 0xffff:
            raise ValueError("ABL body direct lookup exceeds uint16_t")

    lines = [
        "/* Private ABL signing-path interposer control; NEVER flash to BC250. */",
        "#ifndef BC250_SPARSE_PHYSICAL_PROFILE_H",
        "#define BC250_SPARSE_PHYSICAL_PROFILE_H",
        f'#define PROFILE_NAME "{"abl" + str(args.abl_index) + "-" + args.abl_hook_site + "-" + hook_kind if hook else "abl-resign-only"}{"-gasket31" if args.sec_gasket_value is not None else ""}"',
        "#define PROFILE_ROWS 872744u",
        "#define PROFILE_RUNS 37u",
        f"#define PROFILE_CHANGED_WORDS {len(changed)}u",
        f"#define PROFILE_KEY_PATCH_FIRST_INDEX {key_first_index}u",
        *([f"#define PROFILE_KEY31_PATCH_FIRST_INDEX {key31_first_index}u",
           f"#define PROFILE_POLICY_SIG_PATCH_FIRST_INDEX {policy_sig_first_index}u",
           "#define PROFILE_ALLOW_SEC_GASKET 1"] if args.sec_gasket_value is not None else []),
        *[f"#define PROFILE_ABL_SIG{index}_PATCH_FIRST_INDEX {first}u"
          for index, first in enumerate(signature_first_indices)],
        f"#define PROFILE_SECOND_KEYDB_ROW {KEYDB_SECOND_COPY_ROW}u",
        f"#define PROFILE_EXPECTED_PATCH_READS {len(rows)}u",
        "#define PROFILE_ALLOW_ABL_SIGNATURES 1",
        *(["#define PROFILE_ALLOW_ABL0_BODY_HOOK 1",
           "#define PROFILE_DIAG_SPI 1",
           "#define PROFILE_DIAG_CAPACITY 4u"] if hook else []),
        *([f"#define PROFILE_ABL_BODY_START 0x{target:06x}u",
           f"#define PROFILE_ABL_BODY_END 0x{target + 0x100 + ABL_BODY_SIZES[args.abl_index]:06x}u",
           f"#define PROFILE_ABL_BODY_LOOKUP_WORDS {len(body_lookup)}u"]
          if hook else []),
        *(["#define PROFILE_EARLY_DIAG_MARKER 0x03c3fffcu"] if hook_kind == "marker" else []),
        *(["#define PROFILE_EARLY_DIAG_VCN 1"] if hook_kind in ("harvest", "policy", "harvest-clear", "fabric", "fabric-toggle", "fabric-toggle-entry") else []),
        *([f"#define PROFILE_EARLY_DIAG_ROW {ABL_ENTRY_DIAG_ROWS[args.abl_index]}u"]
          if hook_kind in ("harvest", "policy", "harvest-clear", "fabric", "fabric-toggle", "fabric-toggle-entry") else []),
        "static const struct expected_run expected_runs[PROFILE_RUNS] = {" + run_block + "};",
        "static const struct patch_word patch_words[PROFILE_CHANGED_WORDS] = {",
        *[f"    {{0x{command:08x}u, 0x{value:08x}u}}," for command, value in changed],
        "};",
        *(["static const uint16_t profile_abl_body_lookup[PROFILE_ABL_BODY_LOOKUP_WORDS] = {",
           *["    " + ", ".join(f"{slot}u" for slot in body_lookup[offset:offset + 16]) + ","
             for offset in range(0, len(body_lookup), 16)],
           "};"] if hook else []),
        "#endif", "",
    ]
    args.output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    private_write(args.output_dir / "control-NEVER-flash.rom", bytes(modified))
    private_write(args.output_dir / "sparse_physical_profile.h", "\n".join(lines).encode())
    summary = {
        "clean_sha256": ROM_SHA,
        "control_sha256": sha(modified),
        "abl_images": abl_images,
        "entry_hook_kind": hook_kind,
        "hook_site": args.abl_hook_site if hook else None,
        "hook_abl_index": args.abl_index if hook else None,
        "entry_hook_sha256": sha(hook) if hook else None,
        "sec_gasket_value_0x1f820": (hex(args.sec_gasket_value)
                                      if args.sec_gasket_value is not None else None),
        "changed_words": len(changed),
        "key_patch_reads_per_pass": key_patch_reads,
        "signature_patch_reads_per_pass": signature_patch_reads,
        "expected_patch_reads_per_pass": len(rows),
        "first_patch_row": rows[0],
        "last_patch_row": rows[-1],
        "bios_flash_allowed": False,
        "hardware_decode_verified": False,
    }
    private_write(args.output_dir / "summary.json", (json.dumps(summary, indent=2) + "\n").encode())
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
