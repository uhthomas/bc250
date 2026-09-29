#!/usr/bin/env python3
"""Measure VCPU clock status around a reset-held CLK_EN differential.

Builds from the already exercised TMR BAR oracle. The VCPU is explicitly
held in reset while its previously calibrated CLK_EN bit is turned off and
back on. Only volatile VCN registers change; no firmware is flashed.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-tmr-bar-oracle-20260929/vcn_v2_0.c'
SOURCE_SHA = '0d49825d10f006696f45c16ea09b2009e68852e3b17af00cacb890f4f101d5da'
VCN = BUILD / 'vcn-rbc-tmr-bar-oracle-20260929/amdgpu_vcn.c'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'
DEST = BUILD / 'vcn-vcpu-clock-differential-20260929'

RESET_OLD = '''		WREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET,
				 UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
		udelay(10);
		WREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET, 0);'''

RESET_NEW = '''		WREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET,
				 UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
		/* The RBC and host already demonstrated that CLK_EN can be
		 * restored. Probe the VCPU-specific CGC status while reset is
		 * asserted, then restore CLK_EN before the normal release.
		 */
		{
			u32 ctrl_on = RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL);
			u32 cgc_on = RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS);
			u32 gate = RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE);
			u32 cgc_ctrl = RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL);
			u32 ctrl_off, cgc_off, ctrl_back, cgc_back;

			if (ctrl_on != 0x0ff20200 || gate == 0xffffffff ||
			    cgc_ctrl == 0xffffffff)
				return -EINVAL;
			WREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_VCPU_CNTL),
				0, ~UVD_VCPU_CNTL__CLK_EN_MASK);
			udelay(100);
			ctrl_off = RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL);
			cgc_off = RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS);
			WREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_VCPU_CNTL),
				UVD_VCPU_CNTL__CLK_EN_MASK,
				~UVD_VCPU_CNTL__CLK_EN_MASK);
			udelay(100);
			ctrl_back = RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL);
			cgc_back = RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS);
			dev_warn(adev->dev,
				 "BC250 VCPU clock differential: gate=%08x cgcctrl=%08x cgc_on=%08x cgc_off=%08x cgc_back=%08x ctrl_on=%08x ctrl_off=%08x ctrl_back=%08x prid=%08x\\n",
				 gate, cgc_ctrl, cgc_on, cgc_off, cgc_back,
				 ctrl_on, ctrl_off, ctrl_back,
				 RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID));
			if (ctrl_off != (ctrl_on & ~UVD_VCPU_CNTL__CLK_EN_MASK) ||
			    ctrl_back != ctrl_on)
				return -EIO;
		}
		WREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET, 0);
		udelay(100);
		dev_warn(adev->dev,
			 "BC250 VCPU clock released: gate=%08x cgcctrl=%08x cgc=%08x ctrl=%08x prid=%08x pc=%08x status=%08x\\n",
			 RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE),
			 RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL),
			 RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS),
			 RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL),
			 RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),
			 RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
			 RREG32_SOC15(UVD, 0, mmUVD_STATUS));'''

WAIT_OLD = '''		if (adev->pdev->device == 0x13fe && i == 0)
			dev_warn(adev->dev,
				 "BC250 VCN VCPU wait0: pc=%08x pf=%08x latency=%08x\\n",'''
WAIT_NEW = '''		if (adev->pdev->device == 0x13fe && i == 0)
			dev_warn(adev->dev,
				 "BC250 VCPU clock wait0: gate=%08x cgcctrl=%08x cgc=%08x ctrl=%08x prid=%08x\\n",
				 RREG32_SOC15(UVD, 0, mmUVD_CGC_GATE),
				 RREG32_SOC15(UVD, 0, mmUVD_CGC_CTRL),
				 RREG32_SOC15(UVD, 0, mmUVD_CGC_STATUS),
				 RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL),
				 RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID));
		if (adev->pdev->device == 0x13fe && i == 0)
			dev_warn(adev->dev,
				 "BC250 VCN VCPU wait0: pc=%08x pf=%08x latency=%08x\\n",'''


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'VCpu clock differential anchor changed: {old[:72]!r}')
    return source.replace(old, new, 1)


def main() -> None:
    source = SOURCE.read_bytes()
    vcn = VCN.read_bytes()
    if (hashlib.sha256(source).hexdigest() != SOURCE_SHA or
            hashlib.sha256(vcn).hexdigest() != VCN_SHA):
        raise ValueError('pinned TMR BAR source changed')
    text = replace_once(source.decode(), RESET_OLD, RESET_NEW)
    text = replace_once(text, WAIT_OLD, WAIT_NEW)
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in (('vcn_v2_0.c', text.encode()), ('amdgpu_vcn.c', vcn)):
        path = DEST / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_bytes(data)
        print(name, hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    main()
