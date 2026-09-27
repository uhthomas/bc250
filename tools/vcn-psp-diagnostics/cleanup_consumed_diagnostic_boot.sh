#!/usr/bin/env bash
# Remove the already-consumed one-time diagnostic entry on the diagnostic OS.
set -euo pipefail
test "$(uname -r)" = 7.2.5-200.fc44.x86_64
test "$(readlink /proc/self/ns/mnt)" != "$(readlink /proc/1/ns/mnt)"
test "$(sha256sum /boot/grub2/custom.cfg | cut -d ' ' -f1)" = 9675158c6e976ec9fee3741eac39d4a81e128577e62a5684049a6d5a277d6ef9
test "$(grub2-editenv - list)" = bc250_vcn_once=0
test "$(sha256sum /boot/grub2/grub.cfg | cut -d ' ' -f1)" = e189cb8bdde09be81315c3f91a4034eb13c48975a0c5e39dc429cec51fe55772
test "$(sha256sum /boot/loader/entries/ostree-2.conf | cut -d ' ' -f1)" = 0d815d69db1a1522d478afb56f7c400418c42792a2f9edb9117a087b719c39ad
mount -o remount,rw /boot
grub2-editenv - unset bc250_vcn_once
rm -- /boot/grub2/custom.cfg
sync
test -z "$(grub2-editenv - list)"
test ! -e /boot/grub2/custom.cfg
