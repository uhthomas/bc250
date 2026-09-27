#!/usr/bin/env python3
"""Generate a default-off VCN signed-byte tamper probe for a one-time boot.

This emits source and a manifest only. It does not build, install, load or
submit a firmware request. The diagnostic deliberately cannot submit an
unmodified VCN image: it flips one byte inside the signed region while
preserving the header, key ID, length and signature bytes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

ORIGINAL_SHA = "92e8a864dd9fbc8e8ad05aa2f3991bc35ad7fad57b21b529d7a11515fc3d60ba"
AUTH_FUNCTION_SHA = "5a308f071aab47b44bf291ad22bbdb6605dd5bfba36947dcde280037c54d0a6e"
FIRMWARE_SIGNED_LAST_BYTE = 0x6147f


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"expected one source anchor: {old[:80]!r}")
    return source.replace(old, new, 1)


def private_write(path, data):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def generate(original, auth_functions):
    if sha(original) != ORIGINAL_SHA or sha(auth_functions) != AUTH_FUNCTION_SHA:
        raise ValueError("pinned Fedora PSP source or prior auth control changed")
    original, function = original.decode(), auth_functions.decode()
    function = replace_once(function,
        "/* Negative authentication controls only: invalid extent, no decoder MMIO. */",
        "/* Signed-byte tamper only: no valid VCN load or decoder MMIO. */")
    function = replace_once(function,
        "\tstatic const u8 gfx_key[16] = {\n"
        "\t\t0x30, 0xb8, 0x86, 0x51, 0x25, 0x42, 0x44, 0x99,\n"
        "\t\t0xae, 0xff, 0x3a, 0xc3, 0x5c, 0xe6, 0x21, 0xa6,\n"
        "\t};\n", "")
    function = replace_once(function, "(value != 2 && value != 3)", "value != 4")
    function = replace_once(function,
        "\t/* Both variants must fail bounds validation before body copy or hash. */\n"
        "\tput_unaligned_le32(0x200000, payload + 0x14);\n"
        "\tput_unaligned_le32(0, payload + 0x70);\n"
        "\tpayload[0x7f] = 0;\n"
        "\tif (value == 3)\n"
        "\t\tmemcpy(payload + 0x38, gfx_key, sizeof(gfx_key));\n",
        "\t/* Last signed byte: unchanged header/key/signature, invalid body. */\n"
        f"\tpayload[0x{FIRMWARE_SIGNED_LAST_BYTE:x}] ^= 1;\n")
    function = replace_once(function,
        '"BC250 VCN PSP auth: variant=%llu type=%u size=%u extent=0x200000\\n",',
        '"BC250 VCN PSP auth: variant=%llu type=%u size=%u signed_byte_tampered=0x6147f\\n",')
    source = replace_once(original, '#include <linux/firmware.h>\n',
                          '#include <linux/firmware.h>\n#include <linux/pm_runtime.h>\n'
                          '#include <linux/unaligned.h>\n')
    source = replace_once(source,
        '#define AMD_VBIOS_FILE_MAX_SIZE_B      (1024*1024*16)\n',
        '#define AMD_VBIOS_FILE_MAX_SIZE_B      (1024*1024*16)\n\n'
        'static bool bc250_vcn_psp_probe;\n'
        'module_param_named(bc250_vcn_psp_probe, bc250_vcn_psp_probe, bool, 0444);\n'
        'MODULE_PARM_DESC(bc250_vcn_psp_probe,\n'
        '\t\t"Expose BC250 VCN signed-byte tamper probe (default off)");\n')
    source = replace_once(source, '#if defined(CONFIG_DEBUG_FS)\nstatic int psp_read_spirom_debugfs_open',
                          '#if defined(CONFIG_DEBUG_FS)\n' + function +
                          '\nstatic int psp_read_spirom_debugfs_open')
    anchor = '\tstruct drm_minor *minor = adev_to_drm(adev)->primary;\n'
    source = replace_once(source, anchor, anchor + '''
\tif (bc250_vcn_psp_probe &&
\t    adev->asic_type == CHIP_CYAN_SKILLFISH &&
\t    adev->pdev->device == 0x13fe &&
\t    amdgpu_ip_version(adev, VCN_HWIP, 0) == IP_VERSION(2, 0, 3))
\t\tdebugfs_create_file("bc250_vcn_psp_auth", 0200,
\t\t\t\t    minor->debugfs_root, adev,
\t\t\t\t    &bc250_vcn_psp_probe_fops);
''')
    if "value != 4" not in source or "signed_byte_tampered=0x6147f" not in source:
        raise ValueError("tamper probe missing from generated source")
    if "value != 2" in source or "value == 3" in source:
        raise ValueError("prior control variants still exposed")
    return source.encode()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kernel-build", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    args = p.parse_args()
    root = args.kernel_build
    original = (root / "psp-probe-original-amdgpu_psp.c").read_bytes()
    auth = (root / "psp-auth-functions.c").read_bytes()
    source = generate(original, auth)
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    private_write(args.output_dir / "amdgpu_psp.c", source)
    manifest = dict(original_sha256=ORIGINAL_SHA,
                    prior_auth_functions_sha256=AUTH_FUNCTION_SHA,
                    generated_sha256=sha(source),
                    variant=4, tampered_signed_byte=hex(FIRMWARE_SIGNED_LAST_BYTE),
                    valid_vcn_load_exposed=False, decoder_startup_enabled=False,
                    board_access=False, bios_flash_writes=False)
    private_write(args.output_dir / "manifest.json",
                  (json.dumps(manifest, indent=2) + "\n").encode())
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
