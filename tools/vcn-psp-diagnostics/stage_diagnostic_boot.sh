#!/usr/bin/env bash
# Stage exactly one BC250 diagnostic boot from a private mount namespace.
# Invoke with: unshare -m -- bash stage_diagnostic_boot.sh
set -euo pipefail

template=/var/lib/bc250/validation/video-20260922/kernel/psp-test-custom.cfg
entry=/boot/grub2/custom.cfg
expected_template=9675158c6e976ec9fee3741eac39d4a81e128577e62a5684049a6d5a277d6ef9
expected_grub=e189cb8bdde09be81315c3f91a4034eb13c48975a0c5e39dc429cec51fe55772
expected_bls=0d815d69db1a1522d478afb56f7c400418c42792a2f9edb9117a087b719c39ad

test "$(id -u)" = 0
test "$(uname -r)" = 7.2.5-200.fc44.x86_64
test "$(readlink /proc/self/ns/mnt)" != "$(readlink /proc/1/ns/mnt)"
test "$(sha256sum "$template" | cut -d ' ' -f1)" = "$expected_template"
test "$(sha256sum /boot/grub2/grub.cfg | cut -d ' ' -f1)" = "$expected_grub"
test "$(sha256sum /boot/loader/entries/ostree-2.conf | cut -d ' ' -f1)" = "$expected_bls"
test ! -e "$entry"
test -z "$(grub2-editenv - list)"
test "$(findmnt -no OPTIONS /boot | cut -d, -f1)" = ro

mount -o remount,rw /boot
install -m 0644 "$template" "$entry"
test "$(sha256sum "$entry" | cut -d ' ' -f1)" = "$expected_template"
grub2-editenv - set bc250_vcn_once=1
test "$(grub2-editenv - list)" = bc250_vcn_once=1
sync /boot
printf 'Staged one diagnostic boot; mount namespace will close.\n'
