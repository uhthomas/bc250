#!/usr/bin/env python3
"""Generate a guarded, reversible RBC write test for VCPU_REPORT.

The four aligned ring batches assert VCPU reset and try STATUS=2, restore
STATUS=4 and release reset, then repeat the 2/4 pair while released. No
firmware map, BIOS EEPROM, or Pico flash is changed.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-vcpu-address-fault-20260929/vcn_v2_0.c'
SOURCE_SHA = '7be776962f21d5100869f8d986830f0783861eb36524899886a9ebfd7f617a4b'
VCN = BUILD / 'vcn-vcpu-address-fault-20260929/amdgpu_vcn.c'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'
DEST = BUILD / 'vcn-vcpu-report-force-20260929'

PROBE = r'''
	if (adev->pdev->device == 0x13fe) {
		u32 power = RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS);
		u32 pgfsm = RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS);
		u32 version = RREG32_SOC15(UVD, 0, mmUVD_VERSION);
		u32 harvest = RREG32_SOC15(UVD, 0, mmCC_UVD_HARVESTING);
		u32 status = RREG32_SOC15(UVD, 0, mmUVD_STATUS);
		u32 old_cntl = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL);
		u32 old_rptr = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);
		u32 old_wptr = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR);
		u32 idle_cntl, run_cntl, phase, word, rptr, marker;
		unsigned int sample_i;

		dev_warn(adev->dev,
			 "BC250 VCPU report pre: power=%08x pgfsm=%08x version=%08x harvest=%08x status=%08x cntl=%08x rptr=%08x wptr=%08x ring=%llx bytes=%u swptr=%llu vcpu=%08x\n",
			 power, pgfsm, version, harvest, status,
			 old_cntl, old_rptr, old_wptr,
			 (unsigned long long)ring->gpu_addr, ring->ring_size,
			 (unsigned long long)ring->wptr,
			 RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL));
		if (power != 0x800 || pgfsm != 0 || version != 0x2001b ||
		    harvest != 3 || status != 4 || old_cntl != 0x01000101 ||
		    old_rptr != 0 || old_wptr != 0 || ring->wptr != 0 ||
		    !ring->ring || !ring->funcs ||
		    ring->funcs->align_mask != 0xf ||
		    ring->gpu_addr != 0x264000 || ring->ring_size != 4096 ||
		    RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != 0x0ff20200) {
			dev_warn(adev->dev, "BC250 VCPU report guard skipped\n");
			return -EINVAL;
		}

		run_cntl = REG_SET_FIELD(0, UVD_RBC_RB_CNTL, RB_BUFSZ,
					order_base_2(ring->ring_size));
		run_cntl = REG_SET_FIELD(run_cntl, UVD_RBC_RB_CNTL, RB_BLKSZ, 1);
		run_cntl = REG_SET_FIELD(run_cntl, UVD_RBC_RB_CNTL, RB_RPTR_WR_EN, 1);
		idle_cntl = run_cntl | UVD_RBC_RB_CNTL__RB_NO_FETCH_MASK |
					 UVD_RBC_RB_CNTL__RB_NO_UPDATE_MASK;
		WREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_VMID, 0);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, idle_cntl);
		WREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_LOW,
				 lower_32_bits(ring->gpu_addr));
		WREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_HIGH,
				 upper_32_bits(ring->gpu_addr));
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR, 0);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 0);
		WREG32_SOC15(UVD, 0, mmUVD_SCRATCH9, 0xcafedead);
		if (RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL) != idle_cntl ||
		    RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9) != 0xcafedead) {
			WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, old_cntl);
			return -EIO;
		}

		for (phase = 0; phase < 4; ++phase) {
			word = phase * 16;
			marker = 0x11110000 | phase;
			for (sample_i = 0; sample_i < 16; sample_i++)
				WRITE_ONCE(ring->ring[word + sample_i],
					   sample_i & 1 ? 0 :
					   PACKET0(adev->vcn.inst[0].internal.nop, 0));
			if (phase == 0) {
				WRITE_ONCE(ring->ring[word],
					   PACKET0(mmUVD_SOFT_RESET - 0x80, 0));
				WRITE_ONCE(ring->ring[word + 1],
					   UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
				word += 2;
			}
			WRITE_ONCE(ring->ring[word],
				   PACKET0(mmUVD_STATUS - 0x80, 0));
			WRITE_ONCE(ring->ring[word + 1], phase & 1 ? 4 : 2);
			word += 2;
			if (phase == 1) {
				WRITE_ONCE(ring->ring[word],
					   PACKET0(mmUVD_SOFT_RESET - 0x80, 0));
				WRITE_ONCE(ring->ring[word + 1], 0);
				word += 2;
			}
			WRITE_ONCE(ring->ring[word],
				   PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
			WRITE_ONCE(ring->ring[word + 1], marker);
			wmb();
			if (phase == 0)
				WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, run_cntl);
			WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR,
					 (phase + 1) * 16);
			for (sample_i = 0; sample_i < 1024; ++sample_i) {
				rptr = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);
				if (rptr == (phase + 1) * 16 &&
				    RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9) == marker)
					break;
				udelay(5);
			}
			dev_warn(adev->dev,
				 "BC250 VCPU report phase=%u rptr=%08x marker=%08x status=%08x dpg=%08x prid=%08x pc=%08x lmi=%08x\n",
				 phase, RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR),
				 RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9),
				 RREG32_SOC15(UVD, 0, mmUVD_STATUS),
				 RREG32_SOC15(UVD, 0, mmUVD_DPG_CLK_EN_VCPU_REPORT),
				 RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),
				 RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
				 RREG32_SOC15(UVD, 0, mmUVD_LMI_STATUS));
		}
		/* Preserve the driver's pending wait semantics even if a ring
		 * packet failed. This is the value the driver set before our probe.
		 */
		WREG32_SOC15(UVD, 0, mmUVD_STATUS, status);
		WREG32_P(SOC15_REG_OFFSET(UVD, 0, mmUVD_SOFT_RESET), 0,
			~UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
		dev_warn(adev->dev,
			 "BC250 VCPU report final: status=%08x dpg=%08x prid=%08x pc=%08x rptr=%08x\n",
			 RREG32_SOC15(UVD, 0, mmUVD_STATUS),
			 RREG32_SOC15(UVD, 0, mmUVD_DPG_CLK_EN_VCPU_REPORT),
			 RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),
			 RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
			 RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR));
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, idle_cntl);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 0);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR, 0);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, old_cntl);
	}

'''


def main() -> None:
    source = SOURCE.read_bytes()
    vcn = VCN.read_bytes()
    if (hashlib.sha256(source).hexdigest() != SOURCE_SHA or
            hashlib.sha256(vcn).hexdigest() != VCN_SHA):
        raise ValueError('pinned VCPU address-error source changed')
    candidate = source.decode()
    anchor = candidate.index('BC250 VCN LMI requests:')
    start = candidate.index('\n\tif (adev->pdev->device == 0x13fe) {\n', anchor)
    end = candidate.index('\n\tfor (i = 0; i < 10; ++i) {', start)
    if candidate[start:end].count('BC250 VCN RBC cache oracle signed replay:') != 1:
        raise ValueError('unexpected VCN ring oracle boundary')
    candidate = candidate[:start] + '\n' + PROBE + candidate[end:]
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
