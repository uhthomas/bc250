#!/usr/bin/env bash
# Build-time only: keep ACPI tables and initramfs updates in the OS image.
set -euo pipefail

case "${1:-}" in
    firmware)
        rm /usr/lib/dracut/dracut.conf.d/90-bc250-acpi.conf
        ;;
    initramfs)
        # Bazzite's /root points here, but /var contents are omitted from OCI.
        install -d -m 0700 /var/roothome
        images=(/usr/lib/modules/*/initramfs.img)
        for initramfs in "${images[@]}"; do
            [[ -f "$initramfs" ]]
            kernel_dir=${initramfs%/initramfs.img}
            kernel_version=${kernel_dir##*/}
            grep -qx 'CONFIG_ACPI_TABLE_UPGRADE=y' "$kernel_dir/config"
            dracut --force --reproducible --no-hostonly --no-hostonly-cmdline \
                --tmpdir /tmp --add ostree \
                --kver "$kernel_version" "$initramfs"
            listing=$(lsinitrd "$initramfs")
            for table in SSDT-CPU SSDT-PST SSDT-STUBS; do
                grep -q "kernel/firmware/acpi/$table.aml" <<< "$listing"
            done
            modules=$(lsinitrd -m "$initramfs")
            grep -qx ostree <<< "$modules"
        done
        rmdir /var/roothome
        ;;
    *) echo 'ACPI_MODE must be initramfs or firmware' >&2; exit 2 ;;
esac
printf '%s\n' "$1" > /usr/share/bc250/acpi-mode
