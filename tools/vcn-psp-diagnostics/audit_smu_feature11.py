#!/usr/bin/env python3
"""Audit BC250 SMU feature 11 (G6 memory-clock SSC) without board changes.

The pinned SRAM image is a prior live capture. This script checks the exact
image and disassembly before interpreting callback pointers or instructions.
It does not claim that the feature toggle has no possible indirect effects.
"""

import hashlib
import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "output/video-decode-20260922/results/smu-sram.bin"
LISTING = ROOT / "output/video-decode-20260922/decompiled-postincrement/listing.txt"
PMFW_HEADER = ROOT / "output/video-decode-20260922/kernel-build/linux-7.2.5/drivers/gpu/drm/amd/pm/swsmu/inc/pmfw_if/smu_v11_8_pmfw.h"
VG_PMFW_HEADER = ROOT / "output/video-decode-20260922/kernel-build/linux-7.2.5/drivers/gpu/drm/amd/pm/swsmu/inc/pmfw_if/smu_v11_5_pmfw.h"
CAPTURE_SHA256 = "b0385d7c8fbbec2aaa1ce7f635df46315847e9965f13879f7c9df9b774a0ccc0"
LISTING_SHA256 = "ed542af5f4e041d6b498a530584e16676c114881e00af736d615d03f36232ad9"
PMFW_HEADER_SHA256 = "8893329478e28c2f36b0298b2aeb0fc4b5902a77e76e82db57e2884fe0a82966"
VG_PMFW_HEADER_SHA256 = "a356c9a974cbacd66bd4799e83ffad3d6566097bf5c26d48bbcc95bf60f5f2ce"


def checked(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError(f"{path}: SHA256 {actual}, expected {expected}")
    return data


def main() -> None:
    sram = checked(CAPTURE, CAPTURE_SHA256)
    listing = checked(LISTING, LISTING_SHA256).decode("utf-8")
    pmfw_header = checked(PMFW_HEADER, PMFW_HEADER_SHA256).decode("utf-8")
    vg_pmfw_header = checked(VG_PMFW_HEADER, VG_PMFW_HEADER_SHA256).decode("utf-8")
    if "#define FEATURE_G6_SSC_BIT                11 //G6 memory UCLK and UCLK_DIV SS" not in pmfw_header:
        raise ValueError("SMU 11.8 feature-11 name changed")
    if "#define FEATURE_VCN_DPM_BIT           11" not in vg_pmfw_header:
        raise ValueError("Van Gogh SMU 11.5 feature-11 name changed")
    if len(sram) != 0x40000:
        raise ValueError("unexpected SMU SRAM size")

    def word(address: int) -> int:
        return struct.unpack_from("<I", sram, address)[0]

    base = word(0x17374)
    state = word(0x171D4)
    if base != 0xCC98 or state != 0xCEC8:
        raise ValueError("feature or tile-state pointer changed")
    bit = 11
    enabled = word(base + 8)
    desired = word(base)
    on = word(base + 0x10 + 4 * bit)
    off = word(base + 0x110 + 4 * bit)
    if not (desired & enabled & (1 << bit)):
        raise ValueError("feature 11 is not enabled and desired")
    if (on, off) != (0x1D938, 0x1D938):
        raise ValueError("feature-11 callbacks changed")
    if sram[on : on + 8].hex() != "3641000c121df000":
        raise ValueError("feature-11 callback bytes changed")
    for line in (
        "0001d938  entry a1,0x20",
        "0001d93b  movi.n a2,0x1",
        "0001d93d  retw.n",
        "0001edb3  movi.n a10,0xb",
        "0001edb5  call8 0x0001db54",
        "0001edc3  movi.n a10,0x3",
        "0001edc5  call8 0x000241f8",
        "0001edc8  movi.n a10,0x4",
        "0001edca  call8 0x000241f8",
        "0001edd7  movi.n a10,0xb",
        "0001edd9  call8 0x0001db54",
        "0001ee9f  movi.n a10,0x3",
        "0001eea3  call8 0x000241ac",
        "0001eeaa  movi.n a10,0x4",
        "0001eeac  call8 0x000241ac",
    ):
        if line not in listing:
            raise ValueError(f"missing disassembly line: {line}")
    print(json.dumps({
        "capture_sha256": CAPTURE_SHA256,
        "listing_sha256": LISTING_SHA256,
        "feature_table": hex(base),
        "feature_bit": bit,
        "feature_name": "G6_SSC (memory UCLK and UCLK_DIV spread spectrum)",
        "feature_is_vcn_power_gate": False,
        "van_gogh_feature_11": "VCN_DPM (different SMU interface; cannot transfer bit meaning)",
        "pmfw_header_sha256": PMFW_HEADER_SHA256,
        "van_gogh_pmfw_header_sha256": VG_PMFW_HEADER_SHA256,
        "desired_mask_low": hex(desired),
        "enabled_mask_low": hex(enabled),
        "enable_callback": hex(on),
        "disable_callback": hex(off),
        "callback_behavior": "return 1 without a tile or register operation",
        "tile_state_byte": sram[state + 0x19],
        "clock_slot_down": "0x1edb0 checks enabled bit 11 and calls 0x241f8 for slots 3 and 4",
        "clock_slot_up": "0x1edd4 checks enabled bit 11 and calls 0x241ac for slots 3 and 4",
        "physical_decode_verified": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
