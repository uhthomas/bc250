#!/usr/bin/env python3
"""Require pinned live VCN allocations before a PSP-side memory-map trial."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-allocation-trace-20260927/vcn_v2_0.c'
DEST = BUILD / 'vcn-map-guard-20260927/vcn_v2_0.c'
SOURCE_SHA = '11212610175f11c0dfbe0439ef253115bf35441f2fb5edddd8ffb05de88fcfda'
ANCHOR = '\t\treload_ret = psp_execute_ip_fw_load(&adev->psp, ucode);\n'
GUARD = '''		/* The Pico table contains these physical GPU addresses. Refuse to
		 * submit a second PSP load if this boot allocated anything else.
		 */
		if (adev->vcn.inst[0].gpu_addr != 0x000000f41fd00000ULL ||
		    adev->vcn.inst[0].fw_shared.gpu_addr != 0x000000f41fda0000ULL ||
		    adev->vcn.inst[0].fw->size != 405952 ||
		    AMDGPU_GPU_PAGE_ALIGN(adev->vcn.inst[0].fw->size + 4) != 0x64000 ||
		    ucode->tmr_mc_addr_hi != 0xf4 ||
		    ucode->tmr_mc_addr_lo != 0x1fa00000 ||
		    adev->gfx.config.gb_addr_config != 0x00100044) {
			dev_err(adev->dev, "BC250 VCN pinned map mismatch; PSP write skipped\\n");
			return -EINVAL;
		}
		dev_warn(adev->dev, "BC250 VCN pinned map matched before PSP write\\n");
'''


def main():
    data = SOURCE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA
    source = data.decode()
    assert source.count(ANCHOR) == 1
    source = source.replace(ANCHOR, GUARD + ANCHOR, 1)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST)
    print(hashlib.sha256(source.encode()).hexdigest())


if __name__ == '__main__':
    main()
