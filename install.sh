#!/usr/bin/env bash
# Run inside this image from a Fedora live USB, using privileged rootful Podman.
set -euo pipefail

if (( $# != 3 )); then
    echo 'Usage: bc250-install <whole-disk> <hostname> <authorized-keys-file>' >&2
    exit 2
fi
if (( EUID != 0 )); then
    echo 'bc250-install must run as root inside the image container.' >&2
    exit 1
fi

disk=$(readlink -f -- "$1")
machine_hostname=$2
authorized_keys=$(readlink -f -- "$3")
if [[ ! "$machine_hostname" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]]; then
    echo 'Use a hostname of 1–63 lowercase letters, digits and internal hyphens.' >&2
    exit 2
fi
if [[ ! -b "$disk" ]] || [[ "$(lsblk --nodeps --noheadings --output TYPE "$disk")" != disk ]]; then
    echo 'Choose a whole physical disk, not a partition or regular file.' >&2
    exit 2
fi
mountpoints=$(lsblk --noheadings --raw --output MOUNTPOINTS "$disk")
if [[ "$mountpoints" =~ [^[:space:]] ]]; then
    echo 'The disk or one of its partitions is mounted/in use; refusing to erase it.' >&2
    exit 1
fi
if [[ "$(blockdev --getro "$disk")" != 0 ]]; then
    echo 'The destination disk is read-only.' >&2
    exit 1
fi
if [[ ! -d /sys/firmware/efi ]]; then
    echo 'Boot the Fedora live USB in UEFI mode before installing.' >&2
    exit 1
fi
if [[ ! -s "$authorized_keys" ]] || grep -q 'PRIVATE KEY' "$authorized_keys"; then
    echo 'Supply a nonempty authorized_keys file containing public SSH keys only.' >&2
    exit 2
fi
ssh-keygen -l -f "$authorized_keys"

lsblk --nodeps --output PATH,SIZE,MODEL,SERIAL "$disk"
printf 'ACPI provider: %s\n' "$(cat /usr/share/bc250/acpi-mode)"
printf 'This will erase ALL data on %s and install BC-250 as %s without encryption.\n' "$disk" "$machine_hostname"
printf 'Type the full destination disk path to continue: '
read -r confirmation </dev/tty
if [[ "$confirmation" != "$disk" ]]; then
    echo 'Aborted.' >&2
    exit 1
fi

bootc install to-disk --wipe --block-setup=direct --filesystem=ext4 \
    --run-fetch-check --root-ssh-authorized-keys="$authorized_keys" \
    --karg="systemd.hostname=$machine_hostname" "$disk"

printf '\nInstalled. Shut down the live environment, remove the USB and boot the disk.\n'
printf 'Connect over SSH as root using the supplied key, then create your desktop user.\n'
