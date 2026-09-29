#!/usr/bin/env python3
"""Compare mapped VCPU stack/context bytes across a guarded reset release.

This is a read-only witness: no BO contents or firmware are changed. A stable
reset-held control distinguishes host/PSP writes from writes after release.
"""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'output/video-decode-20260922/kernel-build'
SOURCE = BUILD / 'vcn-rbc-tmr-bar-oracle-20260929/vcn_v2_0.c'
SOURCE_SHA = '0d49825d10f006696f45c16ea09b2009e68852e3b17af00cacb890f4f101d5da'
VCN = BUILD / 'vcn-rbc-tmr-bar-oracle-20260929/amdgpu_vcn.c'
VCN_SHA = '67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8'
DEST = BUILD / 'vcn-vcpu-memory-witness-20260929'

INCLUDE_OLD = '#include <linux/delay.h>\n'
INCLUDE_NEW = INCLUDE_OLD + '#include <linux/crc32.h>\n'

HELPER_ANCHOR = '#define VCN_VID_SOC_ADDRESS_2_0'
HELPER = '''/* Read GPU-visible VRAM through the already pinned VCN BO mapping. */
static u32 bc250_vcpu_region_crc(void __iomem *base, u32 len)
{
    u8 bytes[256];
    u32 crc = 0, offset;

    for (offset = 0; offset < len; offset += sizeof(bytes)) {
        memcpy_fromio(bytes, base + offset, sizeof(bytes));
        crc = crc32_le(crc, bytes, sizeof(bytes));
    }
    return crc;
}

'''

RESET_OLD = '''\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET,
\t\t\t\t UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\tudelay(10);
\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET, 0);'''

RESET_NEW = '''\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET,
\t\t\t\t UVD_SOFT_RESET__VCPU_SOFT_RESET_MASK);
\t\t/* The signed TMR/BO map and GPU addresses were guarded above.
\t\t * No ring command runs during this measurement window.
\t\t */
\t\t{
\t\t\tvoid __iomem *bo = (void __iomem *)adev->vcn.inst[0].cpu_addr;
\t\t\tu32 stack0, stack_hold, stack_run;
\t\t\tu32 ctx0, ctx_hold, ctx_run;

\t\t\tif (adev->vcn.inst[0].gpu_addr != 0x000000f41fc00000ULL ||
\t\t\t    adev->vcn.inst[0].fw_shared.gpu_addr !=
\t\t\t\t0x000000f41fd04000ULL || !bo ||
\t\t\t    RREG32_SOC15(UVD, 0, mmUVD_VCPU_CNTL) != 0x0ff20200)
\t\t\t\treturn -EINVAL;
\t\t\tstack0 = bc250_vcpu_region_crc(bo + 0x64000, 0x20000);
\t\t\tctx0 = bc250_vcpu_region_crc(bo + 0x84000, 0x80000);
\t\t\tmdelay(20);
\t\t\tstack_hold = bc250_vcpu_region_crc(bo + 0x64000, 0x20000);
\t\t\tctx_hold = bc250_vcpu_region_crc(bo + 0x84000, 0x80000);
\t\t\tWREG32_SOC15(UVD, 0, mmUVD_SOFT_RESET, 0);
\t\t\tmdelay(20);
\t\t\tstack_run = bc250_vcpu_region_crc(bo + 0x64000, 0x20000);
\t\t\tctx_run = bc250_vcpu_region_crc(bo + 0x84000, 0x80000);
\t\t\tdev_warn(adev->dev,
\t\t\t\t "BC250 VCPU memory witness: stack0=%08x stack_hold=%08x stack_run=%08x ctx0=%08x ctx_hold=%08x ctx_run=%08x status=%08x prid=%08x pc=%08x pf=%08x\\n",
\t\t\t\t stack0, stack_hold, stack_run, ctx0, ctx_hold, ctx_run,
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_STATUS),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_PRID),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_VCPU_TRCE),
\t\t\t\t RREG32_SOC15(UVD, 0, mmUVD_PF_STATUS));
\t\t}'''


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f'VCPU memory witness anchor changed: {old[:70]!r}')
    return source.replace(old, new, 1)


def main() -> None:
    source = SOURCE.read_bytes()
    vcn = VCN.read_bytes()
    if (hashlib.sha256(source).hexdigest() != SOURCE_SHA or
            hashlib.sha256(vcn).hexdigest() != VCN_SHA):
        raise ValueError('pinned TMR BAR oracle source changed')
    candidate = replace_once(source.decode(), INCLUDE_OLD, INCLUDE_NEW)
    candidate = replace_once(candidate, HELPER_ANCHOR, HELPER + HELPER_ANCHOR)
    candidate = replace_once(candidate, RESET_OLD, RESET_NEW)
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
