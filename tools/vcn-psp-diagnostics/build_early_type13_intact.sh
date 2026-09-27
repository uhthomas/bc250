#!/usr/bin/env bash
# Compile the default-off intact VCN request against the pinned Fedora kernel.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
build=$repo/output/video-decode-20260922/kernel-build
tree=$build/linux-7.2.5/drivers/gpu/drm/amd/amdgpu
candidate=$build/early-type13-intact-20260927
source=$tree/amdgpu_psp.c
base_sha=7710ae058d9dbcbee8dfef2273c825565e284cbd8ed39d125f7ef5f1a42624f4
candidate_sha=fcf4c0bae363526651c576e4323dfee2b00afcbf35e51f22956a7447e9742e3e
test "$(sha256sum "$source" | cut -d' ' -f1)" = "$base_sha"
test "$(sha256sum "$candidate/amdgpu_psp.c" | cut -d' ' -f1)" = "$candidate_sha"

backup=$(mktemp "$build/.amdgpu_psp.c.XXXXXX")
cp "$source" "$backup"
restore() {
    cp "$backup" "$source"
    rm -f "$backup"
}
trap restore EXIT
cp "$candidate/amdgpu_psp.c" "$source"

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
            /work/early-type13-intact-20260927/amdgpu-psp-early-intact.ko
        test "$(modinfo -F vermagic /work/early-type13-intact-20260927/amdgpu-psp-early-intact.ko | sed "s/[[:space:]]*$//")" = \
            "7.2.5-200.fc44.x86_64 SMP preempt mod_unload"
    '
sha256sum "$candidate/amdgpu-psp-early-intact.ko"
