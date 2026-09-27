#!/usr/bin/env python3
"""Independently verify a BC250 direct VCN-key external-flash image pair.

Optional readback paths verify two programmed EXTERNAL chips. Read-only: this
does not prove interposer switching, BC250 boot, VCN operation or video decode.
The patched image must NEVER be written to the on-board EEPROM.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--clean-readback", type=Path)
    parser.add_argument("--patched-readback", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    clean = Path(manifest["clean_path"]).read_bytes()
    patched = Path(manifest["patched_path"]).read_bytes()
    donor = Path(manifest["donor_keydb_path"]).read_bytes()
    source = Path(manifest["clean_source_path"]).read_bytes()

    assert len(clean) == len(patched) == len(source) == 0x1000000
    assert clean == source and sha(clean) == BOARD_SHA == manifest["clean_sha256"]
    assert sha(patched) == manifest["patched_sha256"]
    assert sha(donor) == DONOR_SHA == manifest["donor_sha256"]
    assert args.clean_readback is None or args.clean_readback.read_bytes() == clean
    assert args.patched_readback is None or args.patched_readback.read_bytes() == patched

    original_db = clean[DB_OFFSET:DB_OFFSET + DB_SIZE]
    patched_db = patched[DB_OFFSET:DB_OFFSET + DB_SIZE]
    assert sha(original_db) == ORIGINAL_DB_SHA == manifest["original_database_sha256"]
    assert original_db[0x10:0x14] == patched_db[0x10:0x14] == b"$PS1"
    assert original_db[0x108:0x10C] == patched_db[0x108:0x10C] == b"$KDB"
    assert patched_db[:BODY_START] == original_db[:BODY_START]
    assert patched_db[BODY_END:] == original_db[BODY_END:]
    assert sha(original_db[BODY_START:BODY_END]) == original_db[0xD0:0xF0].hex()
    assert sha(patched_db[BODY_START:BODY_END]) != original_db[0xD0:0xF0].hex()

    start = DB_OFFSET + RECORD_OFFSET
    end = start + RECORD_SIZE
    old = clean[start:end]
    new = patched[start:end]
    donor_record = donor[DONOR_RECORD_OFFSET:DONOR_RECORD_OFFSET + RECORD_SIZE]
    assert new == donor_record
    assert sha(old) == ORIGINAL_RECORD_SHA == manifest["original_record_sha256"]
    assert sha(new) == VCN_RECORD_SHA == manifest["replacement_record_sha256"]
    assert struct.unpack_from("<I", old)[0] == struct.unpack_from("<I", new)[0] == RECORD_SIZE
    assert struct.unpack_from("<I", old, 8)[0] == 44
    assert struct.unpack_from("<I", new, 8)[0] == 6
    assert patched[:start] == clean[:start] and patched[end:] == clean[end:]
    assert sum(a != b for a, b in zip(old, new)) == manifest["changed_byte_count"] == 272
    assert manifest["changed_flash_range"] == [hex(start), hex(end)]
    assert manifest["type51_header_and_signature_unchanged"] is True
    assert manifest["patched_body_digest_invalid_alone"] is True
    assert manifest["never_flash_onboard_eeprom"] is True
    assert manifest["physical_trial"] is False
    assert manifest["hardware_decode_verified"] is False
    assert manifest["board_access"] is False
    assert manifest["flash_written"] is False

    print("PASS: clean/patched 16 MiB external-only pair; exact type-51 record change")
    print("clean SHA256", sha(clean))
    print("patched SHA256", sha(patched))
    print("provided readback files matched", bool(args.clean_readback), bool(args.patched_readback))


if __name__ == "__main__":
    main()
