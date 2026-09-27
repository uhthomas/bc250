#!/usr/bin/env python3
"""Build source for one early, deliberately invalid VCN PSP request.

This generator only writes private source and a manifest. The generated
module is default-off and stops graphics initialization after the request.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

BASE_SHA = '7710ae058d9dbcbee8dfef2273c825565e284cbd8ed39d125f7ef5f1a42624f4'
EARLY_FUNCTION = r'''
/* Diagnostic only: firmware is always invalidated before PSP submission. */
static int bc250_vcn_psp_early_probe(struct psp_context *psp)
{
	struct amdgpu_device *adev = psp->adev;
	const struct common_firmware_header *header;
	const struct firmware *fw = NULL;
	struct psp_gfx_cmd_resp *cmd;
	static const u8 vcn_key[16] = {
		0xc3, 0x72, 0x90, 0xc3, 0x10, 0xe6, 0x4a, 0x62,
		0xb0, 0x27, 0xc5, 0x66, 0x95, 0x49, 0x23, 0x68,
	};
	static bool attempted;
	u8 *payload = NULL;
	u32 offset, size;
	int i, ret;

	if (!bc250_vcn_psp_early)
		return 0;
	if (attempted || adev->asic_type != CHIP_CYAN_SKILLFISH ||
	    adev->pdev->vendor != 0x1002 || adev->pdev->device != 0x13fe ||
	    amdgpu_ip_version(adev, VCN_HWIP, 0) != IP_VERSION(2, 0, 3) ||
	    amdgpu_vcn_bc250_experimental(adev) ||
	    adev->firmware.load_type != AMDGPU_FW_LOAD_PSP ||
	    amdgpu_sriov_vf(adev) || adev->no_hw_access ||
	    amdgpu_in_reset(adev) || adev->in_suspend || adev->in_runpm ||
	    psp->boot_time_tmr || psp->autoload_supported ||
	    !psp->tmr_bo || amdgpu_bo_size(psp->tmr_bo) != 4 * PSP_1_MEG ||
	    !psp->fw_pri_buf || !psp->cmd_buf_mem || !psp->fence_buf ||
	    !psp->km_ring.ring_mem) {
		dev_err(adev->dev, "BC250 PSP early: platform guard failed\n");
		return -EINVAL;
	}
	for (i = 0; i < adev->firmware.max_ucodes; i++) {
		if (adev->firmware.ucode[i].tmr_mc_addr_lo ||
		    adev->firmware.ucode[i].tmr_mc_addr_hi) {
			dev_err(adev->dev, "BC250 PSP early: graphics firmware already loaded\n");
			return -EBUSY;
		}
	}
	attempted = true;
	ret = amdgpu_ucode_request(adev, &fw, AMDGPU_UCODE_REQUIRED,
				  "amdgpu/navi10_vcn.bin");
	if (ret)
		goto done;
	if (fw->size < sizeof(*header)) {
		ret = -EINVAL;
		goto done;
	}
	header = (const struct common_firmware_header *)fw->data;
	offset = le32_to_cpu(header->ucode_array_offset_bytes);
	size = le32_to_cpu(header->ucode_size_bytes);
	if (offset != 256 || size != 405696 ||
	    offset > fw->size || size > fw->size - offset ||
	    le32_to_cpu(header->ucode_version) != 0x0811800d ||
	    memcmp(fw->data + offset + 0x38, vcn_key, sizeof(vcn_key)) ||
	    get_unaligned_le32(fw->data + offset + 0x14) != 0x61380 ||
	    get_unaligned_le32(fw->data + offset + 0x70) != 0x1b40 ||
	    fw->data[offset + 0x7f]) {
		ret = -EINVAL;
		goto done;
	}
	payload = kvmemdup(fw->data + offset, size, GFP_KERNEL);
	if (!payload) {
		ret = -ENOMEM;
		goto done;
	}
	/* Last signed byte changed; header, key ID, and signature remain intact. */
	payload[0x6147f] ^= 1;
	ret = psp_copy_fw(psp, payload, size);
	if (ret)
		goto done;
	cmd = acquire_psp_cmd_buf(psp);
	cmd->cmd_id = GFX_CMD_ID_LOAD_IP_FW;
	cmd->cmd.cmd_load_ip_fw.fw_phy_addr_lo = lower_32_bits(psp->fw_pri_mc_addr);
	cmd->cmd.cmd_load_ip_fw.fw_phy_addr_hi = upper_32_bits(psp->fw_pri_mc_addr);
	cmd->cmd.cmd_load_ip_fw.fw_size = size;
	cmd->cmd.cmd_load_ip_fw.fw_type = GFX_FW_TYPE_VCN;
	dev_info(adev->dev,
		 "BC250 PSP early: addr fw=0x%016llx cmd=0x%016llx fence=0x%016llx vram=0x%016llx..0x%016llx gart=0x%016llx..0x%016llx\n",
		 psp->fw_pri_mc_addr, psp->cmd_buf_mc_addr,
		 psp->fence_buf_mc_addr, adev->gmc.vram_start,
		 adev->gmc.vram_end, adev->gmc.gart_start,
		 adev->gmc.gart_end);
	dev_info(adev->dev,
		 "BC250 PSP early: submit type=13 size=%u tamper=0x6147f tmr=0x%llx\n",
		 size, psp->tmr_mc_addr);
	ret = psp_cmd_submit_buf(psp, NULL, cmd, psp->fence_buf_mc_addr);
	dev_info(adev->dev,
		 "BC250 PSP early: ret=%d status=0x%08x fw_addr=0x%08x%08x\n",
		 ret, cmd->resp.status, cmd->resp.fw_addr_hi,
		 cmd->resp.fw_addr_lo);
	release_psp_cmd_buf(psp);
done:
	if (ret)
		dev_info(adev->dev, "BC250 PSP early: probe error=%d\n", ret);
	kvfree(payload);
	amdgpu_ucode_release(&fw);
	/* Do not load graphics firmware after a diagnostic PSP request. */
	return -ECANCELED;
}

'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(data, old, new):
    if data.count(old) != 1:
        raise ValueError(f'expected one source anchor: {old[:70]!r}')
    return data.replace(old, new, 1)


def write_private(path, data):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)


def generate(base, intact=False):
    if sha(base) != BASE_SHA:
        raise ValueError('pinned amdgpu source changed')
    source = base.decode()
    if source.count('#include <linux/unaligned.h>\n') != 1:
        raise ValueError('expected pinned unaligned helper include')
    source = replace_once(source,
        '#define AMD_VBIOS_FILE_MAX_SIZE_B      (1024*1024*16)\n',
        '#define AMD_VBIOS_FILE_MAX_SIZE_B      (1024*1024*16)\n\n'
        'static bool bc250_vcn_psp_early;\n'
        'module_param_named(bc250_vcn_psp_early, bc250_vcn_psp_early, bool, 0444);\n'
        'MODULE_PARM_DESC(bc250_vcn_psp_early,\n'
        '\t\t"Early BC250 signed-byte-tampered VCN PSP probe (default off)");\n')
    source = replace_once(source,
        'static int psp_load_fw(struct amdgpu_device *adev)\n',
        EARLY_FUNCTION + 'static int psp_load_fw(struct amdgpu_device *adev)\n')
    head, tail = source.split('static int psp_load_fw(struct amdgpu_device *adev)\n', 1)
    function, rest = tail.split('static int psp_hw_init(struct amdgpu_ip_block *ip_block)\n', 1)
    function = replace_once(function,
        '\tret = psp_hw_start(psp);\n\tif (ret)\n\t\tgoto failed;\n\n'
        '\tret = psp_load_non_psp_fw(psp);',
        '\tret = psp_hw_start(psp);\n\tif (ret)\n\t\tgoto failed;\n\n'
        '\tret = bc250_vcn_psp_early_probe(psp);\n'
        '\tif (ret)\n\t\tgoto failed1;\n\n'
        '\tret = psp_load_non_psp_fw(psp);')
    source = (head + 'static int psp_load_fw(struct amdgpu_device *adev)\n' +
              function + 'static int psp_hw_init(struct amdgpu_ip_block *ip_block)\n' + rest)
    if source.count('BC250 PSP early: submit type=13') != 1:
        raise ValueError('early request is absent or duplicated')
    if intact:
        source = replace_once(source,
            '/* Diagnostic only: firmware is always invalidated before PSP submission. */',
            '/* Diagnostic only: submit intact firmware and stop graphics initialization. */')
        source = replace_once(source,
            '\t/* Last signed byte changed; header, key ID, and signature remain intact. */\n'
            '\tpayload[0x6147f] ^= 1;\n',
            '\t/* The signed firmware payload is left intact. */\n')
        source = replace_once(source, 'tamper=0x6147f', 'tamper=none')
        source = replace_once(source,
            'Early BC250 signed-byte-tampered VCN PSP probe (default off)',
            'Early BC250 intact VCN PSP probe (default off)')
    return source.encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--intact', action='store_true',
                        help='Submit the pinned VCN firmware without changing signed bytes')
    args = parser.parse_args()
    source = generate((args.kernel_build / 'linux-7.2.5/drivers/gpu/drm/amd/amdgpu/amdgpu_psp.c').read_bytes(),
                      intact=args.intact)
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_private(args.output_dir / 'amdgpu_psp.c', source)
    manifest = {'base_sha256': BASE_SHA, 'source_sha256': sha(source),
                'firmware': 'navi10_vcn.bin', 'firmware_type': 13,
                'tamper_offset': None if args.intact else '0x6147f',
                'default_off': True,
                'stops_graphics_init': True, 'bios_flash_writes': False}
    write_private(args.output_dir / 'manifest.json',
                  (json.dumps(manifest, indent=2) + '\n').encode())
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
