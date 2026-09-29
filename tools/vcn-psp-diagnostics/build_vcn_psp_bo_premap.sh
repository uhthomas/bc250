#!/usr/bin/env bash
# Build the guarded delayed ordinary-BO VCN map diagnostic module.
# The installed bootc image and both flash devices are never written.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
build=$repo/output/video-decode-20260922/kernel-build
tree=$build/linux-7.2.5/drivers/gpu/drm/amd/amdgpu
candidate=$build/vcn-psp-bo-premap-20260929
late=$build/late-psp-probe-20260927

test "$(sha256sum "$tree/amdgpu_psp.c" | cut -d' ' -f1)" = \
    7710ae058d9dbcbee8dfef2273c825565e284cbd8ed39d125f7ef5f1a42624f4
test "$(sha256sum "$tree/amdgpu_vcn.c" | cut -d' ' -f1)" = \
    8390fdcdc7b258507f9954ead0e3635f6eae5dfc954c28fa1b5240fc32a88bf9
test "$(sha256sum "$tree/vcn_v2_0.c" | cut -d' ' -f1)" = \
    e75a0427f18662884b4f8251167bb693608da7f17bfefd2225ee17707738fbef
test "$(sha256sum "$late/amdgpu_psp.c" | cut -d' ' -f1)" = \
    9d574280fa9f76b6adbec4c3fb971a2c16e9c8614a150b07c8e92759f5a3e62e
python3 "$repo/tools/vcn-psp-diagnostics/prepare_vcn_psp_bo_premap.py"
test "$(sha256sum "$candidate/amdgpu_vcn.c" | cut -d' ' -f1)" = \
    67861711fc08ba47eacb594a623b7e250669621ee5587052b90b0074b2af66e8
test "$(sha256sum "$candidate/vcn_v2_0.c" | cut -d' ' -f1)" = \
    477779c79dc8659549e9b580c018cbdc846feaea71c97bab8bfa3520f3de620d

backup_psp=$(mktemp "$build/.amdgpu_psp.c.XXXXXX")
backup_vcn=$(mktemp "$build/.amdgpu_vcn.c.XXXXXX")
backup_v2=$(mktemp "$build/.vcn_v2_0.c.XXXXXX")
cp "$tree/amdgpu_psp.c" "$backup_psp"
cp "$tree/amdgpu_vcn.c" "$backup_vcn"
cp "$tree/vcn_v2_0.c" "$backup_v2"
restore() {
    cp "$backup_psp" "$tree/amdgpu_psp.c"
    cp "$backup_vcn" "$tree/amdgpu_vcn.c"
    cp "$backup_v2" "$tree/vcn_v2_0.c"
    rm -f "$backup_psp" "$backup_vcn" "$backup_v2"
}
trap restore EXIT
cp "$late/amdgpu_psp.c" "$tree/amdgpu_psp.c"
cp "$candidate/amdgpu_vcn.c" "$tree/amdgpu_vcn.c"
cp "$candidate/vcn_v2_0.c" "$tree/vcn_v2_0.c"

image=localhost/bc250-vcn-builder:20260922
test "$(podman image inspect --format '{{.Id}}' "$image")" = \
    78b2b1cd586f3dded13b36d7a77d0b0ca81704dca1c82c03943a0e7b33a0fa17
podman --runtime=runc run --rm --network=none --cpus=4 --memory=8g \
    --security-opt=label=disable --userns=keep-id \
    -v "$build:/work" \
    "$image" \
    bash -euc '
        release=7.2.5-200.fc44.x86_64
        headers=/usr/src/kernels/$release
        tree=/work/linux-7.2.5/drivers/gpu/drm/amd/amdgpu
        test "$(make -s -C "$headers" kernelrelease)" = "$release"
        make -C "$headers" M="$tree" \
            KCFLAGS=-I/work/linux-7.2.5/include/trace -j4 modules
        objcopy --strip-debug "$tree/amdgpu.ko" \
            /work/vcn-psp-bo-premap-20260929/amdgpu-vcn-psp-bo-premap.ko
        test "$(modinfo -F vermagic /work/vcn-psp-bo-premap-20260929/amdgpu-vcn-psp-bo-premap.ko | sed "s/[[:space:]]*$//")" = \
            "7.2.5-200.fc44.x86_64 SMP preempt mod_unload"
    '
sha256sum "$candidate/amdgpu-vcn-psp-bo-premap.ko"
