#!/usr/bin/env python3
"""Release BC250 VCPU reset through the calibrated ring at boot time.

The ordinary host reset register reads all ones on this board. This one-boot
module sends reset hold/release packets immediately after the signed PSP
firmware-map replay, before the driver's LMI release and first VCPU wait.
It changes no BIOS or Pico flash contents.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-psp-bo-fetch-20260929/vcn_v2_0.c'
SOURCE_SHA = '3652327700e4c05132ad0f9ee2ceb3bc4a6f4991981f36d96ff58aedf75c9f1b'
VCN = BUILD / 'vcn-psp-bo-fetch-20260929/amdgpu_vcn.c'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'
DEST = BUILD / 'vcn-early-ring-reset-20260930b'

ANCHOR_START = '\t/* On this BC250 UVD_SOFT_RESET reads as all ones.'
ANCHOR_END = '\t/* enable LMI MC and UMC channels */'

PROBE = r'''
	/* The ring's 0x1e0 reset route and scratch route have both been
	 * calibrated separately. Execute the reset pair at the original boot
	 * release point, after the signed PSP firmware-map replay.
	 */
	if (adev->pdev->device == 0x13fe) {
		u32 old_cntl = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL);
		u32 run_cntl, idle_cntl, first_rptr, second_rptr;
		u32 first_scratch, second_scratch, dpg, status;
		unsigned int packet_i, sample_i;

		if (RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS) != 0x800 ||
		    RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS) != 0 ||
		    RREG32_SOC15(UVD, 0, mmUVD_VERSION) != 0x2001b ||
		    RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != 0x0ff20200 ||
		    adev->firmware.ucode[AMDGPU_UCODE_ID_VCN].tmr_mc_addr_hi != 0xf4 ||
		    adev->firmware.ucode[AMDGPU_UCODE_ID_VCN].tmr_mc_addr_lo != 0x1fa00000 ||
		    !ring->ring || !ring->funcs || ring->funcs->align_mask != 0xf ||
		    ring->gpu_addr != 0x264000 || ring->ring_size != 4096 ||
		    ring->wptr != 0 ||
		    RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR) != 0 ||
		    RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR) != 0) {
			dev_err(adev->dev, "BC250 VCN early ring reset guard skipped\n");
			return -EINVAL;
		}

		run_cntl = REG_SET_FIELD(0, UVD_RBC_RB_CNTL, RB_BUFSZ,
					order_base_2(ring->ring_size));
		run_cntl = REG_SET_FIELD(run_cntl, UVD_RBC_RB_CNTL, RB_BLKSZ, 1);
		run_cntl = REG_SET_FIELD(run_cntl, UVD_RBC_RB_CNTL,
					RB_RPTR_WR_EN, 1);
		idle_cntl = run_cntl | UVD_RBC_RB_CNTL__RB_NO_FETCH_MASK |
				 UVD_RBC_RB_CNTL__RB_NO_UPDATE_MASK;
		dev_warn(adev->dev,
			 "BC250 VCN early ring preflight: old=%08x run=%08x idle=%08x addr=%016llx size=%u\n",
			 old_cntl, run_cntl, idle_cntl,
			 (unsigned long long)ring->gpu_addr, ring->ring_size);
		if (run_cntl != 0x1000010c || idle_cntl != 0x1101010c) {
			dev_err(adev->dev, "BC250 VCN early ring reset control mismatch\n");
			return -EINVAL;
		}
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, idle_cntl);
		WREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_VMID, 0);
		WREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_LOW,
				 lower_32_bits(ring->gpu_addr));
		WREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_HIGH,
				 upper_32_bits(ring->gpu_addr));
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR, 0);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 0);
		WREG32_SOC15(UVD, 0, mmUVD_SCRATCH9, 0xcafedead);
		for (packet_i = 0; packet_i < 32; packet_i += 2) {
			WRITE_ONCE(ring->ring[packet_i],
				   PACKET0(adev->vcn.inst[0].internal.nop, 0));
			WRITE_ONCE(ring->ring[packet_i + 1], 0);
		}
		WRITE_ONCE(ring->ring[0], PACKET0(mmUVD_SOFT_RESET - 0x80, 0));
		WRITE_ONCE(ring->ring[1], UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
		WRITE_ONCE(ring->ring[2],
			   PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
		WRITE_ONCE(ring->ring[3], 0x11112222);
		WRITE_ONCE(ring->ring[16], PACKET0(mmUVD_SOFT_RESET - 0x80, 0));
		WRITE_ONCE(ring->ring[17], 0);
		WRITE_ONCE(ring->ring[18],
			   PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
		WRITE_ONCE(ring->ring[19], 0x33334444);
		wmb();
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, run_cntl);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 16);
		for (sample_i = 0; sample_i < 1024; ++sample_i) {
			if (RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR) == 16 &&
			    RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9) == 0x11112222)
				break;
			udelay(5);
		}
		first_rptr = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);
		first_scratch = RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9);
		if (first_rptr != 16 || first_scratch != 0x11112222)
			goto early_ring_restore;
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 32);
		for (sample_i = 0; sample_i < 1024; ++sample_i) {
			if (RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR) == 32 &&
			    RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9) == 0x33334444)
				break;
			udelay(5);
		}
		udelay(50);
early_ring_restore:
		second_rptr = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);
		second_scratch = RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9);
		dpg = RREG32_SOC15(UVD, 0, mmUVD_DPG_CLK_EN_VCPU_REPORT);
		status = RREG32_SOC15(UVD, 0, mmUVD_STATUS);
		dev_warn(adev->dev,
			 "BC250 VCN early ring reset: first=%08x/%08x second=%08x/%08x dpg=%08x status=%08x prid=%08x pc=%08x\n",
			 first_rptr, first_scratch, second_rptr, second_scratch,
			 dpg, status,
			 RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),
			 RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE));
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, idle_cntl);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 0);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR, 0);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, old_cntl);
		if (first_rptr != 16 || first_scratch != 0x11112222 ||
		    second_rptr != 32 || second_scratch != 0x33334444)
			return -EIO;
	} else {
		WREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_SOFT_RESET), 0,
			~UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
	}

'''


def main() -> None:
    source = SOURCE.read_bytes()
    vcn = VCN.read_bytes()
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA or \
       hashlib.sha256(vcn).hexdigest() != VCN_SHA:
        raise ValueError('pinned VCN source changed')
    candidate = source.decode()
    if candidate.count(ANCHOR_START) != 1:
        raise ValueError('early reset anchors changed')
    start = candidate.index(ANCHOR_START)
    if candidate.count(ANCHOR_END, start) != 1:
        raise ValueError('early reset end anchor changed')
    end = candidate.index(ANCHOR_END, start)
    candidate = candidate[:start] + PROBE + candidate[end:]
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in (('vcn_v2_0.c', candidate.encode()),
                       ('amdgpu_vcn.c', vcn)):
        path = DEST / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_bytes(data)
        print(name, hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    main()
