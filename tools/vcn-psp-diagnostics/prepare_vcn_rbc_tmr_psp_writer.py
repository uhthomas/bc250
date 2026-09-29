#!/usr/bin/env python3
"""Build a guarded RBC read test for sixteen PSP-written video-TMR words.

The signed RAM-only PSP hook writes only the last page of the allocated
video-TMR region. This kernel probe first proves a normal-BO RBC control,
then fetches the same-sized packet stream from TMR and restores the ring BAR.
Neither BIOS EEPROM nor Pico QSPI flash is written.
"""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-vcpu-report-force-20260929/vcn_v2_0.c'
SOURCE_SHA = 'd69ab73839c4458c1ca88959479010991908dd6492dc9bf4769e356a20bfabc0'
VCN = BUILD / 'vcn-vcpu-report-force-20260929/amdgpu_vcn.c'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'
DEST = BUILD / 'vcn-rbc-tmr-psp-writer-20260929'

PROBE = r'''
	if (adev->pdev->device == 0x13fe) {
		u64 tmr = ((u64)adev->firmware.ucode[AMDGPU_UCODE_ID_VCN].tmr_mc_addr_hi << 32) |
			  adev->firmware.ucode[AMDGPU_UCODE_ID_VCN].tmr_mc_addr_lo;
		u32 power = RREG32_SOC15(UVD, 0, mmUVD_POWER_STATUS);
		u32 pgfsm = RREG32_SOC15(UVD, 0, mmUVD_PGFSM_STATUS);
		u32 status = RREG32_SOC15(UVD, 0, mmUVD_STATUS);
		u32 writer = RREG32_SOC15(UVD, 0, mmUVD_SCRATCH1);
		u32 old_cntl = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL);
		u32 old_rptr = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);
		u32 old_wptr = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR);
		u32 old_lo = RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_LOW);
		u32 old_hi = RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_HIGH);
		u32 old_vmid = RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_VMID);
		u32 old_scratch = RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9);
		u32 run_cntl, idle_cntl, rptr = 0, marker = 0;
		unsigned int sample_i;
		bool control_ok = false, tmr_ok = false;

		dev_warn(adev->dev,
			 "BC250 TMR RBC pre: power=%08x pgfsm=%08x status=%08x writer=%08x tmr=%016llx cntl=%08x rptr=%08x wptr=%08x bar=%08x%08x vmid=%08x ring=%llx bytes=%u\n",
			 power, pgfsm, status, writer, (unsigned long long)tmr,
			 old_cntl, old_rptr, old_wptr, old_hi, old_lo, old_vmid,
			 (unsigned long long)ring->gpu_addr, ring->ring_size);
		if (power != 0x800 || pgfsm != 0 || status != 4 ||
		    RREG32_SOC15(UVD, 0, mmUVD_VERSION) != 0x2001b ||
		    writer != 0x7a000010 || tmr != 0x000000f41fa00000ULL ||
		    old_cntl != 0x01000101 || old_rptr != 0 || old_wptr != 0 ||
		    ring->wptr != 0 || !ring->ring || !ring->funcs ||
		    ring->funcs->align_mask != 0xf ||
		    ring->gpu_addr != 0x264000 || ring->ring_size != 4096) {
			dev_warn(adev->dev, "BC250 TMR RBC guard skipped\n");
			return -EINVAL;
		}

		run_cntl = REG_SET_FIELD(0, UVD_RBC_RB_CNTL, RB_BUFSZ,
					order_base_2(ring->ring_size));
		run_cntl = REG_SET_FIELD(run_cntl, UVD_RBC_RB_CNTL, RB_BLKSZ, 1);
		run_cntl = REG_SET_FIELD(run_cntl, UVD_RBC_RB_CNTL, RB_RPTR_WR_EN, 1);
		idle_cntl = run_cntl | UVD_RBC_RB_CNTL__RB_NO_FETCH_MASK |
					 UVD_RBC_RB_CNTL__RB_NO_UPDATE_MASK;
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, idle_cntl);
		WREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_VMID, 0);
		WREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_LOW,
				 lower_32_bits(ring->gpu_addr));
		WREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_HIGH,
				 upper_32_bits(ring->gpu_addr));
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR, 0);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 0);
		WREG32_SOC15(UVD, 0, mmUVD_SCRATCH9, 0xcafedead);
		for (sample_i = 0; sample_i < 16; sample_i++)
			WRITE_ONCE(ring->ring[sample_i],
				   sample_i & 1 ? 0 :
				   PACKET0(adev->vcn.inst[0].internal.nop, 0));
		WRITE_ONCE(ring->ring[0],
			   PACKET0(adev->vcn.inst[0].internal.scratch9, 0));
		WRITE_ONCE(ring->ring[1], 0x7b2500c0);
		wmb();
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, run_cntl);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 16);
		for (sample_i = 0; sample_i < 1024; ++sample_i) {
			rptr = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);
			marker = RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9);
			if (rptr == 16 && marker == 0x7b2500c0) {
				control_ok = true;
				break;
			}
			udelay(5);
		}
		dev_warn(adev->dev,
			 "BC250 TMR RBC BO control: ok=%u rptr=%08x marker=%08x bar=%08x%08x\n",
			 control_ok, rptr, marker,
			 RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_HIGH),
			 RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_LOW));

		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, idle_cntl);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 0);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR, 0);
		if (control_ok) {
			WREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_LOW, 0x1faff000);
			WREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_HIGH, 0xf4);
			WREG32_SOC15(UVD, 0, mmUVD_SCRATCH9, 0xcafedead);
			if (RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_LOW) == 0x1faff000 &&
			    RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_HIGH) == 0xf4) {
				WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, run_cntl);
				WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 16);
				for (sample_i = 0; sample_i < 1024; ++sample_i) {
					rptr = RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR);
					marker = RREG32_SOC15(UVD, 0, mmUVD_SCRATCH9);
					if (rptr == 16 && marker == 0x7b250001) {
						tmr_ok = true;
						break;
					}
					udelay(5);
				}
			}
		}
		dev_warn(adev->dev,
			 "BC250 TMR RBC PSP packets: ok=%u rptr=%08x marker=%08x bar=%08x%08x status=%08x pc=%08x\n",
			 tmr_ok, rptr, marker,
			 RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_HIGH),
			 RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_LOW),
			 RREG32_SOC15(UVD, 0, mmUVD_STATUS),
			 RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE));
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, idle_cntl);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR, 0);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR, 0);
		WREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_LOW, old_lo);
		WREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_HIGH, old_hi);
		WREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_VMID, old_vmid);
		WREG32_SOC15(UVD, 0, mmUVD_SCRATCH9, old_scratch);
		WREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL, old_cntl);
		dev_warn(adev->dev,
			 "BC250 TMR RBC restored: cntl=%08x bar=%08x%08x vmid=%08x rptr=%08x wptr=%08x\n",
			 RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_CNTL),
			 RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_HIGH),
			 RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_64BIT_BAR_LOW),
			 RREG32_SOC15(UVD, 0, mmUVD_LMI_RBC_RB_VMID),
			 RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_RPTR),
			 RREG32_SOC15(UVD, 0, mmUVD_RBC_RB_WPTR));
		if (!control_ok || !tmr_ok)
			return -EIO;
	}

'''


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f'PSP TMR probe anchor changed: {old[:75]!r}')
    return text.replace(old, new, 1)


def main() -> None:
    source = SOURCE.read_bytes()
    vcn = VCN.read_bytes()
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA or \
            hashlib.sha256(vcn).hexdigest() != VCN_SHA:
        raise ValueError('pinned VCN trial source changed')
    candidate = source.decode()
    candidate = replace_once(candidate,
        '\t\tdev_warn(adev->dev, "BC250 VCN pinned BO and payload matched before PSP write\\n");\n'
        '\t\treload_ret = psp_execute_ip_fw_load(&adev->psp, ucode);',
        '\t\tdev_warn(adev->dev, "BC250 VCN pinned BO and payload matched before PSP write\\n");\n'
        '\t\tWREG32_SOC15(UVD, 0, mmUVD_SCRATCH1, 0x5a13c0df);\n'
        '\t\treload_ret = psp_execute_ip_fw_load(&adev->psp, ucode);')
    candidate = replace_once(candidate,
        '\t\tif (reload_ret || adev->psp.cmd_buf_mem->resp.status ||\n'
        '\t\t    (ucode->tmr_mc_addr_hi == 0 && ucode->tmr_mc_addr_lo == 0)) {',
        '\t\tdev_warn(adev->dev, "BC250 TMR PSP writer result=%08x\\n",\n'
        '\t\t\t RREG32_SOC15(UVD, 0, mmUVD_SCRATCH1));\n'
        '\t\tif (reload_ret || adev->psp.cmd_buf_mem->resp.status ||\n'
        '\t\t    RREG32_SOC15(UVD, 0, mmUVD_SCRATCH1) != 0x7a000010 ||\n'
        '\t\t    (ucode->tmr_mc_addr_hi == 0 && ucode->tmr_mc_addr_lo == 0)) {')
    anchor = candidate.index('BC250 VCN LMI requests:')
    start = candidate.index('\n\tif (adev->pdev->device == 0x13fe) {\n', anchor)
    end = candidate.index('\n\tfor (i = 0; i < 10; ++i) {', start)
    if candidate[start:end].count('BC250 VCPU report phase=') != 1:
        raise ValueError('unexpected old ring probe boundary')
    candidate = candidate[:start] + '\n' + PROBE + candidate[end:]
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in (('vcn_v2_0.c', candidate.encode()), ('amdgpu_vcn.c', vcn)):
        path = DEST / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f'candidate changed: {path}')
        if not path.exists():
            path.write_bytes(data)
        print(name, hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    main()
