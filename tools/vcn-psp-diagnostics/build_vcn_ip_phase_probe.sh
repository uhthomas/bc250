#!/usr/bin/env bash
# Build an opt-in BC250 VCN IP-init trace without changing the installed image.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
build=$repo/output/video-decode-20260922/kernel-build
tree=$build/linux-7.2.5/drivers/gpu/drm/amd/amdgpu
candidate=$build/vcn-ip-phase-20260929
late=$build/late-psp-probe-20260927
direct=$build/vcn-direct-bo-powered-20260928
phase=$build/vcn-startup-phase-20260929
test "$(sha256sum "$tree/amdgpu_device.c" | cut -d' ' -f1)" = \
    42b089ec977648f19c780d90c3eca271306c5826b62e4a7ac0bb5a3904f8c876
test "$(sha256sum "$tree/amdgpu_psp.c" | cut -d' ' -f1)" = \
    7710ae058d9dbcbee8dfef2273c825565e284cbd8ed39d125f7ef5f1a42624f4
test "$(sha256sum "$tree/amdgpu_vcn.c" | cut -d' ' -f1)" = \
    8390fdcdc7b258507f9954ead0e3635f6eae5dfc954c28fa1b5240fc32a88bf9
test "$(sha256sum "$tree/vcn_v2_0.c" | cut -d' ' -f1)" = \
    e75a0427f18662884b4f8251167bb693608da7f17bfefd2225ee17707738fbef
test "$(sha256sum "$late/amdgpu_psp.c" | cut -d' ' -f1)" = \
    9d574280fa9f76b6adbec4c3fb971a2c16e9c8614a150b07c8e92759f5a3e62e
test "$(sha256sum "$direct/amdgpu_vcn.c" | cut -d' ' -f1)" = \
    971c2f10e199bd51a749ac0083b411ffb24bb3e85daf8637038b64900078b7a3
test "$(sha256sum "$phase/vcn_v2_0.c" | cut -d' ' -f1)" = \
    cb53502f48d393a59565853f98c6a804e48635c24e14b6aeff86a4190fb4d5eb
python3 "$repo/tools/vcn-psp-diagnostics/prepare_vcn_ip_phase_probe.py"
test "$(sha256sum "$candidate/amdgpu_device.c" | cut -d' ' -f1)" = \
    6196cb620375497c10bcdf0ae5debac0d13d1eb5bb698b08a553cf587d03639c

backup_device=$(mktemp "$build/.amdgpu_device.c.XXXXXX")
backup_psp=$(mktemp "$build/.amdgpu_psp.c.XXXXXX")
backup_vcn=$(mktemp "$build/.amdgpu_vcn.c.XXXXXX")
backup_v2=$(mktemp "$build/.vcn_v2_0.c.XXXXXX")
cp "$tree/amdgpu_device.c" "$backup_device"
cp "$tree/amdgpu_psp.c" "$backup_psp"
cp "$tree/amdgpu_vcn.c" "$backup_vcn"
cp "$tree/vcn_v2_0.c" "$backup_v2"
restore() {
    cp "$backup_device" "$tree/amdgpu_device.c"
    cp "$backup_psp" "$tree/amdgpu_psp.c"
    cp "$backup_vcn" "$tree/amdgpu_vcn.c"
    cp "$backup_v2" "$tree/vcn_v2_0.c"
    rm -f "$backup_device" "$backup_psp" "$backup_vcn" "$backup_v2"
}
trap restore EXIT
cp "$candidate/amdgpu_device.c" "$tree/amdgpu_device.c"
cp "$late/amdgpu_psp.c" "$tree/amdgpu_psp.c"
cp "$direct/amdgpu_vcn.c" "$tree/amdgpu_vcn.c"
cp "$phase/vcn_v2_0.c" "$tree/vcn_v2_0.c"

podman --runtime=runc run --rm --network=none --cpus=4 --memory=8g \
    --security-opt=label=disable --userns=keep-id -v "$build:/work" \
    78b2b1cd586f3dded13b36d7a77d0b0ca81704dca1c82c03943a0e7b33a0fa17 \
    bash -euc '
        release=7.2.5-200.fc44.x86_64
        headers=/usr/src/kernels/$release
        tree=/work/linux-7.2.5/drivers/gpu/drm/amd/amdgpu
        test "$(make -s -C "$headers" kernelrelease)" = "$release"
        make -C "$headers" M="$tree" \
            KCFLAGS=-I/work/linux-7.2.5/include/trace -j4 modules
        objcopy --strip-debug "$tree/amdgpu.ko" \
            /work/vcn-ip-phase-20260929/amdgpu-vcn-ip-phase.ko
        test "$(modinfo -F vermagic /work/vcn-ip-phase-20260929/amdgpu-vcn-ip-phase.ko | sed "s/[[:space:]]*$//")" = \
            "7.2.5-200.fc44.x86_64 SMP preempt mod_unload"
    '
sha256sum "$candidate/amdgpu-vcn-ip-phase.ko"
