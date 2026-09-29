#!/usr/bin/env python3
"""Test VCPU release with a displaced TMR firmware BAR, then restore it.

The existing signed PSP oracle proves the BAR shift before VCPU release and
the full map restoration afterward. All changes are volatile ring packets.
An unchanged VCPU trace is inconclusive because a bad fetch may fail silently.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-tmr-bar-oracle-20260929/vcn_v2_0.c'
SOURCE_SHA = '0d49825d10f006696f45c16ea09b2009e68852e3b17af00cacb890f4f101d5da'
VCN = BUILD / 'vcn-rbc-tmr-bar-oracle-20260929/amdgpu_vcn.c'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'
DEST = BUILD / 'vcn-fetch-bar-differential-20260929'

START = '\t\tfor (sample_i = 16; sample_i < 32; ++sample_i)\n'
END = '\t\t/* Read the restored BAR before the signed driver\'s map replay.\n'
REPLACEMENT = r'''		/* Put cache size back before release so the only deliberately
		 * wrong firmware-map field during the test is BAR_LOW. The prior
		 * PSP sentinel has already authenticated the 64 KiB displacement.
		 */
		for (sample_i = 16; sample_i < 32; ++sample_i)
			WRITE_ONCE(ring->ring[sample_i], sample_i & 1 ? 0 :
				   PACKET0(adev->vcn.inst[0].internal.nop, 0));
		WRITE_ONCE(ring->ring[16], PACKET0(mmUVD_VCPU_CACHE_SIZE0 - 0x80, 0));
		WRITE_ONCE(ring->ring[17], 0x64000);
		WRITE_ONCE(ring->ring[18], PACKET0(mmUVD_SOFT_RESET - 0x80, 0));
		WRITE_ONCE(ring->ring[19], 0);
		WRITE_ONCE(ring->ring[20], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
		WRITE_ONCE(ring->ring[21], 0x22223333);
		wmb();
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 32);
		for (sample_i = 0; sample_i < 1024; ++sample_i) {
			if (RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR) == 32 &&
			    RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9) == 0x22223333)
				break;
			udelay(5);
		}
		dev_warn(adev->dev,
			 "BC250 VCN RBC cache oracle second: cntl=%08x rptr=%08x scratch=%08x status=%08x\n",
			 RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL),
			 RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR),
			 RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9),
			 RREG32_SOC15(UVD, 0, mmUVD_STATUS));
		{
			u32 status0 = RREG32_SOC15(UVD, 0, mmUVD_STATUS);
			u32 status_or = status0;
			u32 pc_or = RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE);
			u32 pf_or = RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS);

			for (sample_i = 0; sample_i < 4096; ++sample_i) {
				status_or |= RREG32_SOC15(UVD, 0, mmUVD_STATUS);
				pc_or |= RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE);
				pf_or |= RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS);
				udelay(5);
			}
			dev_warn(adev->dev,
				 "BC250 VCPU fetch differential displaced: status0=%08x status_or=%08x pc_or=%08x pf_or=%08x status=%08x pc=%08x pf=%08x prid=%08x lmi=%08x latency=%08x\n",
				 status0, status_or, pc_or, pf_or,
				 RREG32_SOC15(UVD, 0, mmUVD_STATUS),
				 RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
				 RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS),
				 RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),
				 RREG32_SOC15(UVD, 0, mmUVD_LMI_STATUS),
				 RREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CNTR));
		}

		/* Reassert reset before restoring the authenticated TMR BAR.
		 * Release again with the good BAR for a same-boot comparison.
		 */
		for (sample_i = 32; sample_i < 48; ++sample_i)
			WRITE_ONCE(ring->ring[sample_i], sample_i & 1 ? 0 :
				   PACKET0(adev->vcn.inst[0].internal.nop, 0));
		WRITE_ONCE(ring->ring[32], PACKET0(mmUVD_SOFT_RESET - 0x80, 0));
		WRITE_ONCE(ring->ring[33], UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
		WRITE_ONCE(ring->ring[34],
			   PACKET0(mmUVD_LMI_VCPU_CACHE_64BIT_BAR_LOW - 0x80, 0));
		WRITE_ONCE(ring->ring[35], 0x1fa00000);
		WRITE_ONCE(ring->ring[36], PACKET0(mmUVD_VCPU_CACHE_SIZE0 - 0x80, 0));
		WRITE_ONCE(ring->ring[37], 0x64000);
		WRITE_ONCE(ring->ring[38], PACKET0(mmUVD_SOFT_RESET - 0x80, 0));
		WRITE_ONCE(ring->ring[39], 0);
		WRITE_ONCE(ring->ring[40], PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
		WRITE_ONCE(ring->ring[41], 0x33334444);
		wmb();
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 48);
		for (sample_i = 0; sample_i < 1024; ++sample_i) {
			if (RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR) == 48 &&
			    RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9) == 0x33334444)
				break;
			udelay(5);
		}
		dev_warn(adev->dev,
			 "BC250 VCN RBC cache oracle third: cntl=%08x rptr=%08x scratch=%08x status=%08x\n",
			 RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL),
			 RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR),
			 RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9),
			 RREG32_SOC15(UVD, 0, mmUVD_STATUS));
		{
			u32 status0 = RREG32_SOC15(UVD, 0, mmUVD_STATUS);
			u32 status_or = status0;
			u32 pc_or = RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE);
			u32 pf_or = RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS);

			for (sample_i = 0; sample_i < 4096; ++sample_i) {
				status_or |= RREG32_SOC15(UVD, 0, mmUVD_STATUS);
				pc_or |= RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE);
				pf_or |= RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS);
				udelay(5);
			}
			dev_warn(adev->dev,
				 "BC250 VCPU fetch differential restored: status0=%08x status_or=%08x pc_or=%08x pf_or=%08x status=%08x pc=%08x pf=%08x prid=%08x lmi=%08x latency=%08x\n",
				 status0, status_or, pc_or, pf_or,
				 RREG32_SOC15(UVD, 0, mmUVD_STATUS),
				 RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
				 RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS),
				 RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),
				 RREG32_SOC15(UVD, 0, mmUVD_LMI_STATUS),
				 RREG32_SOC15(UVD, 0, mmUVD_LMI_LAT_CNTR));
		}

'''


def main() -> None:
    source = SOURCE.read_bytes()
    vcn = VCN.read_bytes()
    if (hashlib.sha256(source).hexdigest() != SOURCE_SHA or
            hashlib.sha256(vcn).hexdigest() != VCN_SHA):
        raise ValueError('pinned TMR BAR oracle source changed')
    decoded = source.decode()
    if decoded.count(START) != 1 or decoded.count(END) != 1:
        raise ValueError('TMR BAR oracle insertion point changed')
    begin = decoded.index(START)
    end = decoded.index(END, begin)
    candidate = (decoded[:begin] + REPLACEMENT + decoded[end:]).encode()
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in (('vcn_v2_0.c', candidate), ('amdgpu_vcn.c', vcn)):
        path = DEST / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_bytes(data)
        print(name, hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    main()
