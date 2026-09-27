#!/usr/bin/env python3
"""Prepare RAM-only type-51 copy-read profiles from the measured BC250 trace.

The first profile replies with one byte-for-byte original flash word to test
the physical handover. The second substitutes the 69 changed VCN-key words
only during the type-51 copy read; the later hash read uses original flash.
Neither profile contains an erase/program command or writes the BIOS.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from analyze_full_cs_stream import expand
from prepare_sparse_profile import compress

TRACE_SHA = "b3c22dd2d6d8bd43d8f6b696717e87b46e853e22bf837d93cbb831f48349a5ed"
CLEAN_SHA = "f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183"
PATCHED_SHA = "cd41a46f7fa8d64e40d2a4250eb3baae24eaf17202d7a293d3f1fc2919895781"
SCOPE_ROWS = 873480
COPY_ROW = 872744
HASH_ROW = 873080


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_private(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(content)


def make_header(name, runs, changes):
    lines = ["/* RAM-only profile generated from a measured physical trace. */",
             "#ifndef BC250_SPARSE_PHYSICAL_PROFILE_H",
             "#define BC250_SPARSE_PHYSICAL_PROFILE_H",
             f'#define PROFILE_NAME "{name}"',
             f"#define PROFILE_ROWS {SCOPE_ROWS}u",
             f"#define PROFILE_RUNS {len(runs)}u",
             f"#define PROFILE_CHANGED_WORDS {len(changes)}u",
             "#define PROFILE_SECOND_KEYDB_ROW 696u",
             f"#define PROFILE_TYPE51_HASH_ROW {HASH_ROW}u",
             f"#define PROFILE_EXPECTED_PATCH_READS {len(changes)}u",
             "static const struct expected_run expected_runs[PROFILE_RUNS] = {"]
    lines += [f"    {{0x{command:08x}u, {count}u}}," for command, count in runs]
    lines += ["};", "static const struct patch_word patch_words[PROFILE_CHANGED_WORDS] = {"]
    lines += [f"    {{0x{command:08x}u, 0x{reply:08x}u}}," for command, reply in changes]
    return "\n".join(lines + ["};", "#endif", ""])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--clean", required=True, type=Path)
    parser.add_argument("--patched", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    binary = args.binary.read_bytes()
    metadata = json.loads(args.metadata.read_text())
    clean, patched = args.clean.read_bytes(), args.patched.read_bytes()
    if (sha(binary), sha(clean), sha(patched)) != (TRACE_SHA, CLEAN_SHA, PATCHED_SHA):
        raise ValueError("trace or ROM hash differs from the pinned inputs")
    commands = expand(binary, metadata)
    anchors = [i for i, command in enumerate(commands) if command == 0x039db040]
    if len(anchors) != 4:
        raise ValueError(f"expected four type-50 anchors, got {len(anchors)}")
    scope = commands[anchors[0]:anchors[0] + SCOPE_ROWS]
    if scope != commands[anchors[2]:anchors[2] + SCOPE_ROWS]:
        raise ValueError("two boot passes differ within the type-51 scope")
    if (scope[COPY_ROW], scope[HASH_ROW]) != (0x039dbb00, 0x039dbc00):
        raise ValueError("type-51 copy/hash geometry differs")
    runs = compress(scope)
    if len(runs) != 39 or len(scope) != SCOPE_ROWS:
        raise ValueError("unexpected command run geometry")
    if scope[COPY_ROW:COPY_ROW + 336] != [0x039dbb00 + 4*i for i in range(336)]:
        raise ValueError("type-51 copy read differs")
    if scope[HASH_ROW:HASH_ROW + 400] != [0x039dbc00 + 4*i for i in range(400)]:
        raise ValueError("type-51 hash read differs")
    changes = [(0x03000000 | address,
                int.from_bytes(patched[address:address+4], "big"))
               for address in range(0x9dbda0, 0x9dbef0, 4)
               if clean[address:address+4] != patched[address:address+4]]
    if len(changes) != 69:
        raise ValueError(f"expected 69 changed key words, got {len(changes)}")
    if any(scope[COPY_ROW:HASH_ROW].count(command) != 1 for command, _ in changes):
        raise ValueError("changed word absent or repeated in type-51 copy read")
    control_address = 0x9dbda8
    control = [(0x03000000 | control_address,
                int.from_bytes(clean[control_address:control_address+4], "big"))]
    for name, words in (("type51-original-control", control),
                        ("type51-vcn-copy", changes)):
        directory = args.output_dir / name
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        write_private(directory / "sparse_physical_profile.h", make_header(name, runs, words))
        summary = dict(name=name, trace_sha256=TRACE_SHA,
                       scope_sha256=sha(b"".join(c.to_bytes(4, "little") for c in scope)),
                       clean_sha256=CLEAN_SHA, patched_sha256=PATCHED_SHA,
                       rows=SCOPE_ROWS, runs=len(runs),
                       type51_copy_row=COPY_ROW, type51_hash_row=HASH_ROW,
                       substitution_words=len(words),
                       expected_reply_per_boot_pass=len(words),
                       bios_flash_writes=False)
        write_private(directory / "profile.json", json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary))


if __name__ == "__main__":
    main()
