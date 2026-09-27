#!/usr/bin/env bash
# Build the pinned VCN PSP path with an opt-in late firmware/register probe.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
build=$repo/output/video-decode-20260922/kernel-build
tree=$build/linux-7.2.5/drivers/gpu/drm/amd/amdgpu
candidate=$build/late-psp-probe-20260927
vcn=$build/vcn-psp-driver-20260927
test "$(sha256sum "$tree/amdgpu_psp.c" | cut -d' ' -f1)" = \
    7710ae058d9dbcbee8dfef2273c825565e284cbd8ed39d125f7ef5f1a42624f4
test "$(sha256sum "$tree/amdgpu_vcn.c" | cut -d' ' -f1)" = \
    8390fdcdc7b258507f9954ead0e3635f6eae5dfc954c28fa1b5240fc32a88bf9
test "$(sha256sum "$candidate/amdgpu_psp.c" | cut -d' ' -f1)" = \
    9d574280fa9f76b6adbec4c3fb971a2c16e9c8614a150b07c8e92759f5a3e62e
test "$(sha256sum "$vcn/amdgpu_vcn.c" | cut -d' ' -f1)" = \
    6fc1584109ef3b782b37a211a84585e21b1a8268e624adff86370dbdaaa8d983

backup_psp=$(mktemp "$build/.amdgpu_psp.c.XXXXXX")
backup_vcn=$(mktemp "$build/.amdgpu_vcn.c.XXXXXX")
cp "$tree/amdgpu_psp.c" "$backup_psp"
cp "$tree/amdgpu_vcn.c" "$backup_vcn"
restore() {
    cp "$backup_psp" "$tree/amdgpu_psp.c"
    cp "$backup_vcn" "$tree/amdgpu_vcn.c"
    rm -f "$backup_psp" "$backup_vcn"
}
trap restore EXIT
cp "$candidate/amdgpu_psp.c" "$tree/amdgpu_psp.c"
cp "$vcn/amdgpu_vcn.c" "$tree/amdgpu_vcn.c"

podman --runtime=runc run --rm --network=none --cpus=4 --memory=8g \
    --security-opt=label=disable --userns=keep-id \
    -v "$build:/work" \
    78b2b1cd586f3dded13b36d7a77d0b0ca81704dca1c82c03943a0e7b33a0fa17 \
    bash -euc '
        release=7.2.5-200.fc44.x86_64
        headers=/usr/src/kernels/$release
        tree=/work/linux-7.2.5/drivers/gpu/drm/amd/amdgpu
        test "$(make -s -C "$headers" kernelrelease)" = "$release"
        make -C "$headers" M="$tree" \
            KCFLAGS=-I/work/linux-7.2.5/include/trace -j4 modules
        objcopy --strip-debug "$tree/amdgpu.ko" \
            /work/late-psp-probe-20260927/amdgpu-vcn-late-psp-probe.ko
        test "$(modinfo -F vermagic /work/late-psp-probe-20260927/amdgpu-vcn-late-psp-probe.ko | sed "s/[[:space:]]*$//")" = \
            "7.2.5-200.fc44.x86_64 SMP preempt mod_unload"
        modinfo -F parm /work/late-psp-probe-20260927/amdgpu-vcn-late-psp-probe.ko |
            grep -F "bc250_vcn_psp_probe:Expose BC250 VCN PSP load probe (default off)"
    '
sha256sum "$candidate/amdgpu-vcn-late-psp-probe.ko"
