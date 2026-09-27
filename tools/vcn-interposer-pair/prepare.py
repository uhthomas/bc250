#!/usr/bin/env python3
"""Prepare a private BC250 external-flash pair for direct VCN key substitution.

The patched image is signature-invalid as a standalone ROM. NEVER write it to
the on-board EEPROM. Only a verified, isolated two-flash interposer can present
its changed type-51 body for the copy read and the clean body for verification.
This script writes files under a private local directory; it accesses no board.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile

if not __debug__:
    raise RuntimeError("Python -O disables the image safety checks")

BOARD_SHA = "f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183"
DONOR_SHA = "4a26b8467520d76d86ed09d989a5142bb5766eee26172f789c0ffe0378bce459"
ORIGINAL_DB_SHA = "1ca4d22f6eb87b0806aeb3061e0e4a31c567ea2c1b21df3d2132a1c4b90c0ede"
ORIGINAL_RECORD_SHA = "2c0fa3fdb7b40386b0253740397fbd7328d77cef5069ee8b3080ae9c8abb2afc"
VCN_RECORD_SHA = "eba62408d67693e923a309ce62f108b563f78f02cb7f18b24a3ed060bc8ece58"
DB_OFFSET, DB_SIZE = 0x9DBB00, 0x740
RECORD_OFFSET, RECORD_SIZE = 0x2A0, 0x150
DONOR_RECORD_OFFSET = 0xA30
BODY_START, BODY_END = 0x100, 0x540


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def write_private(path, blob):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(blob)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-rom", required=True, type=Path)
    parser.add_argument("--donor-keydb", required=True, type=Path)
    parser.add_argument("--out-parent", type=Path, default=Path("/tmp"))
    args = parser.parse_args()

    clean = args.clean_rom.read_bytes()
    donor = args.donor_keydb.read_bytes()
    assert len(clean) == 0x1000000 and sha(clean) == BOARD_SHA
    assert sha(donor) == DONOR_SHA
    original_db = clean[DB_OFFSET:DB_OFFSET + DB_SIZE]
    assert len(original_db) == DB_SIZE and sha(original_db) == ORIGINAL_DB_SHA
    assert original_db[0x10:0x14] == b"$PS1"
    assert original_db[0x108:0x10C] == b"$KDB"
    assert sha(original_db[BODY_START:BODY_END]) == original_db[0xD0:0xF0].hex()

    old = original_db[RECORD_OFFSET:RECORD_OFFSET + RECORD_SIZE]
    vcn = donor[DONOR_RECORD_OFFSET:DONOR_RECORD_OFFSET + RECORD_SIZE]
    assert len(old) == len(vcn) == RECORD_SIZE
    assert sha(old) == ORIGINAL_RECORD_SHA and sha(vcn) == VCN_RECORD_SHA
    assert struct.unpack_from("<I", old)[0] == struct.unpack_from("<I", vcn)[0] == RECORD_SIZE
    assert struct.unpack_from("<I", old, 8)[0] == 44
    assert struct.unpack_from("<I", vcn, 8)[0] == 6

    start = DB_OFFSET + RECORD_OFFSET
    end = start + RECORD_SIZE
    patched = clean[:start] + vcn + clean[end:]
    patched_db = patched[DB_OFFSET:DB_OFFSET + DB_SIZE]
    assert len(patched) == len(clean)
    assert patched_db[:BODY_START] == original_db[:BODY_START]
    assert patched_db[BODY_END:] == original_db[BODY_END:]
    assert sha(patched_db[BODY_START:BODY_END]) != original_db[0xD0:0xF0].hex()
    changed = sum(a != b for a, b in zip(old, vcn))
    assert changed == 272

    out = Path(tempfile.mkdtemp(prefix="bc250-vcn-direct-pair-", dir=args.out_parent))
    os.chmod(out, 0o700)
    clean_path = out / "CLEAN-external-flash-only.rom"
    patched_path = out / "PATCHED-interposer-only-NEVER-flash-on-board.rom"
    write_private(clean_path, clean)
    write_private(patched_path, patched)
    manifest = {
        "scope": __doc__,
        "clean_source_path": str(args.clean_rom.resolve()),
        "donor_keydb_path": str(args.donor_keydb.resolve()),
        "clean_path": str(clean_path),
        "patched_path": str(patched_path),
        "clean_sha256": sha(clean),
        "patched_sha256": sha(patched),
        "donor_sha256": sha(donor),
        "original_database_sha256": sha(original_db),
        "original_record_sha256": sha(old),
        "replacement_record_sha256": sha(vcn),
        "changed_flash_range": [hex(start), hex(end)],
        "changed_byte_count": changed,
        "type51_header_and_signature_unchanged": True,
        "patched_body_digest_invalid_alone": True,
        "replacement_usage": 6,
        "displaced_usage": 44,
        "never_flash_onboard_eeprom": True,
        "intended_use": "Two isolated EXTERNAL flash chips with verified active interposer ONLY",
        "physical_trial": False,
        "hardware_decode_verified": False,
        "board_access": False,
        "flash_written": False,
    }
    write_private(out / "MANIFEST.json", (json.dumps(manifest, indent=2) + "\n").encode())
    print("PREPARED external-flash-only pair:", out)
    print("CLEAN SHA256", sha(clean))
    print("PATCHED SHA256", sha(patched))
    print("changed bytes", changed)
    print("NO BOARD EEPROM WRITE; patched image invalid without interposer")


if __name__ == "__main__":
    main()
