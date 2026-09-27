#!/usr/bin/env bash
# Compile the BC250-only opt-in VCN 2.0.3 driver using PSP firmware loading.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
build=$repo/output/video-decode-20260922/kernel-build
tree=$build/linux-7.2.5/drivers/gpu/drm/amd/amdgpu
candidate=$build/vcn-psp-driver-20260927
source=$tree/amdgpu_vcn.c
base_sha=8390fdcdc7b258507f9954ead0e3635f6eae5dfc954c28fa1b5240fc32a88bf9
candidate_sha=6fc1584109ef3b782b37a211a84585e21b1a8268e624adff86370dbdaaa8d983
test "$(sha256sum "$source" | cut -d' ' -f1)" = "$base_sha"
test "$(sha256sum "$candidate/amdgpu_vcn.c" | cut -d' ' -f1)" = "$candidate_sha"
test "$(sha256sum "$tree/amdgpu_psp.c" | cut -d' ' -f1)" = \
    7710ae058d9dbcbee8dfef2273c825565e284cbd8ed39d125f7ef5f1a42624f4

backup=$(mktemp "$build/.amdgpu_vcn.c.XXXXXX")
cp "$source" "$backup"
restore() {
    cp "$backup" "$source"
    rm -f "$backup"
}
trap restore EXIT
cp "$candidate/amdgpu_vcn.c" "$source"

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
            /work/vcn-psp-driver-20260927/amdgpu-vcn-psp.ko
        test "$(modinfo -F vermagic /work/vcn-psp-driver-20260927/amdgpu-vcn-psp.ko | sed "s/[[:space:]]*$//")" = \
            "7.2.5-200.fc44.x86_64 SMP preempt mod_unload"
    '
sha256sum "$candidate/amdgpu-vcn-psp.ko"
