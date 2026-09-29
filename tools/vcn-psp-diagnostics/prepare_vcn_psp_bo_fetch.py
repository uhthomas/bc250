#!/usr/bin/env python3
"""Build source for a guarded PSP-authenticated, ordinary-BO VCN fetch trial.

The PSP still authenticates its VCN image. On this opt-in BC250 build, Linux
also stages the same payload in the VCPU BO. A separate signed RAM-only PSP
hook must program the VCPU cache windows to that BO after power-up.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
VCN_INPUT = BUILD / 'vcn-psp-driver-20260927/amdgpu_vcn.c'
V2_INPUT = BUILD / 'vcn-direct-reset-after-psp-20260928/vcn_v2_0.c'
DEST = BUILD / 'vcn-psp-bo-fetch-20260929'
VCN_SHA = '6fc1584109ef3b782b37a211a84585e21b1a8268e624adff86370dbdaaa8d983'
V2_SHA = '700ce6297e2bbac55a8317159ce209d3ca42743e43f5d3154498a67f9de17c88'
BO = 0x000000f41fc00000
SHARED = 0x000000f41fd04000


def read_pinned(path: Path, expected: str) -> str:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f'pinned source changed: {path}')
    return data.decode()


def replace_one(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'{label}: expected one exact source span, found {source.count(old)}')
    return source.replace(old, new, 1)


def main() -> None:
    vcn = read_pinned(VCN_INPUT, VCN_SHA)
    v2 = read_pinned(V2_INPUT, V2_SHA)

    vcn = replace_one(
        vcn,
        '\tbo_size = AMDGPU_VCN_STACK_SIZE + AMDGPU_VCN_CONTEXT_SIZE;\n'
        '\tif (!amdgpu_vcn_fw_load_via_psp(adev))\n'
        '\t\tbo_size += AMDGPU_GPU_PAGE_ALIGN(le32_to_cpu(hdr->ucode_size_bytes) + 8);',
        '\tbo_size = AMDGPU_VCN_STACK_SIZE + AMDGPU_VCN_CONTEXT_SIZE;\n'
        '\t/* Keep PSP authentication, but reserve an ordinary firmware BO too. */\n'
        '\tif (!amdgpu_vcn_fw_load_via_psp(adev) || adev->pdev->device == 0x13fe)\n'
        '\t\tbo_size += AMDGPU_GPU_PAGE_ALIGN(le32_to_cpu(hdr->ucode_size_bytes) + 8);',
        'reserve firmware BO')
    vcn = replace_one(
        vcn,
        '\tadev->vcn.inst[i].fw_shared.gpu_addr = adev->vcn.inst[i].gpu_addr +\n'
        '\t\tbo_size - fw_shared_size;\n\n'
        '\tadev->vcn.inst[i].fw_shared.mem_size = fw_shared_size;',
        '\tadev->vcn.inst[i].fw_shared.gpu_addr = adev->vcn.inst[i].gpu_addr +\n'
        '\t\tbo_size - fw_shared_size;\n\n'
        '\t/* The RAM-only PSP map table contains these addresses. Abort in\n'
        '\t * SW init, before the first PSP firmware load, if they move.\n'
        '\t */\n'
        '\tif (adev->pdev->device == 0x13fe &&\n'
        f'\t    (adev->vcn.inst[i].gpu_addr != 0x{BO:016x}ULL ||\n'
        f'\t     adev->vcn.inst[i].fw_shared.gpu_addr != 0x{SHARED:016x}ULL ||\n'
        '\t     adev->vcn.inst[i].fw->size != 405952 ||\n'
        '\t     AMDGPU_GPU_PAGE_ALIGN(le32_to_cpu(hdr->ucode_size_bytes) + 8) != 0x64000)) {\n'
        '\t\tdev_err(adev->dev, "BC250 PSP/BO address guard failed before firmware load\\n");\n'
        '\t\treturn -EINVAL;\n'
        '\t}\n\n'
        '\tadev->vcn.inst[i].fw_shared.mem_size = fw_shared_size;',
        'guard firmware BO allocation')
    vcn = replace_one(
        vcn,
        '\t\thdr = (const struct common_firmware_header *)adev->vcn.inst[i].fw->data;\n'
        '\t\tif (!amdgpu_vcn_fw_load_via_psp(adev)) {\n'
        '\t\t\toffset = le32_to_cpu(hdr->ucode_array_offset_bytes);',
        '\t\thdr = (const struct common_firmware_header *)adev->vcn.inst[i].fw->data;\n'
        '\t\tif (!amdgpu_vcn_fw_load_via_psp(adev) || adev->pdev->device == 0x13fe) {\n'
        '\t\t\toffset = le32_to_cpu(hdr->ucode_array_offset_bytes);',
        'stage firmware payload in BO')

    dpg_start = v2.index('static void vcn_v2_0_mc_resume_dpg_mode(')
    static_mc, dpg_and_rest = v2[:dpg_start], v2[dpg_start:]
    static_mc = replace_one(
        static_mc,
        '\t/* cache window 0: fw */\n'
        '\tif (amdgpu_vcn_fw_load_via_psp(adev)) {',
        '\t/* cache window 0: firmware BO on this guarded BC250 trial. */\n'
        '\tif (amdgpu_vcn_fw_load_via_psp(adev) && adev->pdev->device != 0x13fe) {',
        'select ordinary BO cache window')
    v2 = static_mc + dpg_and_rest
    v2 = replace_one(
        v2,
        '\t\tif (adev->vcn.inst[0].gpu_addr != 0x000000f41fd00000ULL ||\n'
        '\t\t    adev->vcn.inst[0].fw_shared.gpu_addr != 0x000000f41fda0000ULL ||',
        f'\t\tif (adev->vcn.inst[0].gpu_addr != 0x{BO:016x}ULL ||\n'
        f'\t\t    adev->vcn.inst[0].fw_shared.gpu_addr != 0x{SHARED:016x}ULL ||',
        'guard powered BO allocation')
    v2 = replace_one(
        v2,
        '\t\tdev_warn(adev->dev, "BC250 VCN pinned map matched before PSP write\\n");\n'
        '\t\treload_ret = psp_execute_ip_fw_load(&adev->psp, ucode);',
        '\t\t/* Copy was staged by amdgpu_vcn_resume. Check the first\n'
        '\t\t * sixteen BO bytes before asking the PSP to map it.\n'
        '\t\t */\n'
        '\t\t{\n'
        '\t\t\tu8 prefix[16];\n'
        '\t\t\tmemcpy_fromio(prefix, adev->vcn.inst[0].cpu_addr, sizeof(prefix));\n'
        '\t\t\tif (memcmp(prefix, "POWERED BY AMD\\r\\n", sizeof(prefix))) {\n'
        '\t\t\t\tdev_err(adev->dev, "BC250 VCN BO firmware prefix mismatch\\n");\n'
        '\t\t\t\treturn -EIO;\n'
        '\t\t\t}\n'
        '\t\t}\n'
        '\t\tdev_warn(adev->dev, "BC250 VCN pinned BO and payload matched before PSP write\\n");\n'
        '\t\treload_ret = psp_execute_ip_fw_load(&adev->psp, ucode);',
        'guard copied payload')

    DEST.mkdir(parents=True, exist_ok=True)
    for name, source in (('amdgpu_vcn.c', vcn), ('vcn_v2_0.c', v2)):
        target = DEST / name
        if target.exists() and target.read_text() != source:
            raise ValueError(f'existing candidate differs: {target}')
        if not target.exists():
            target.write_text(source)
        print(name, hashlib.sha256(source.encode()).hexdigest())


if __name__ == '__main__':
    main()
