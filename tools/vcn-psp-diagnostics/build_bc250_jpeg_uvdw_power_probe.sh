#!/usr/bin/env bash
# Build the isolated JPEG/UVDW power-request module without changing bootc.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
build=$repo/output/video-decode-20260922/kernel-build
tree=$build/linux-7.2.5/drivers/gpu/drm/amd/amdgpu
candidate=$build/bc250-jpeg-uvdw-power-20260929
test "$(sha256sum "$tree/amdgpu_discovery.c" | cut -d' ' -f1)" = \
    136d3add115e1b6afc0dac317ca25084313066a027bc54088f1f2221af786beb
test "$(sha256sum "$tree/jpeg_v2_0.c" | cut -d' ' -f1)" = \
    cd4b62c10aa403e73346c89afd5fa93cd71e0a734453c08cdb4c665be88f451e
python3 "$repo/tools/vcn-psp-diagnostics/prepare_bc250_jpeg_uvdw_power_probe.py"

backup_discovery=$(mktemp "$build/.amdgpu_discovery.c.XXXXXX")
backup_jpeg=$(mktemp "$build/.jpeg_v2_0.c.XXXXXX")
cp "$tree/amdgpu_discovery.c" "$backup_discovery"
cp "$tree/jpeg_v2_0.c" "$backup_jpeg"
restore() {
    cp "$backup_discovery" "$tree/amdgpu_discovery.c"
    cp "$backup_jpeg" "$tree/jpeg_v2_0.c"
    rm -f "$backup_discovery" "$backup_jpeg"
}
trap restore EXIT
cp "$candidate/amdgpu_discovery.c" "$tree/amdgpu_discovery.c"
cp "$candidate/jpeg_v2_0.c" "$tree/jpeg_v2_0.c"

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
            /work/bc250-jpeg-uvdw-power-20260929/amdgpu-bc250-jpeg-uvdw-power.ko
        test "$(modinfo -F vermagic /work/bc250-jpeg-uvdw-power-20260929/amdgpu-bc250-jpeg-uvdw-power.ko | sed "s/[[:space:]]*$//")" = \
            "7.2.5-200.fc44.x86_64 SMP preempt mod_unload"
    '
sha256sum "$candidate/amdgpu-bc250-jpeg-uvdw-power.ko"
