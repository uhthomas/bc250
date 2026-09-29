#!/usr/bin/env python3
"""Record the VCN memory-window values before the PSP post-cache readback."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-postcache-reload-20260927/vcn_v2_0.c'
DEST = BUILD / 'vcn-allocation-trace-20260927/vcn_v2_0.c'
SOURCE_SHA = '650f7499d43ebd4de2174afa8391f0b32f26afe821c4100e4cf4a294b5ef8df8'
ANCHOR = '''static void vcn_v2_0_mc_resume(struct amdgpu_vcn_inst *vinst)
{
	struct amdgpu_device *adev = vinst->adev;
	uint32_t size = AMDGPU_GPU_PAGE_ALIGN(adev->vcn.inst[0].fw->size + 4);
	uint32_t offset;

	if (amdgpu_sriov_vf(adev))
		return;
'''
INSERT = '''
	if (adev->pdev->device == 0x13fe)
		dev_warn(adev->dev,
			 "BC250 VCN allocation: bo=%016llx shared=%016llx fw_bytes=%zu cache0_size=%08x stack=%08x context=%08x shared_size=%08x gfx_config=%08x\\n",
			 (unsigned long long)adev->vcn.inst[0].gpu_addr,
			 (unsigned long long)adev->vcn.inst[0].fw_shared.gpu_addr,
			 adev->vcn.inst[0].fw->size, size,
			 AMDGPU_VCN_STACK_SIZE, AMDGPU_VCN_CONTEXT_SIZE,
			 (u32)AMDGPU_GPU_PAGE_ALIGN(sizeof(struct amdgpu_fw_shared)),
			 adev->gfx.config.gb_addr_config);
'''


def main():
    data = SOURCE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA
    source = data.decode()
    assert source.count(ANCHOR) == 1
    source = source.replace(ANCHOR, ANCHOR + INSERT, 1)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(source)
    print(DEST)
    print(hashlib.sha256(source.encode()).hexdigest())


if __name__ == '__main__':
    main()
