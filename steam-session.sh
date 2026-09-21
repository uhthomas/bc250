#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == --client ]]; then
    # Gamescope has now assigned the display sockets. Propagate these to desktop
    # portals and other D-Bus-activated applications launched by Steam/Flatpak.
    dbus-update-activation-environment --systemd \
        DISPLAY WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE
    exec steam -gamepadui
fi
if (( $# != 0 )); then
    echo 'Usage: bc250-steam-session' >&2
    exit 2
fi

# SDDM/logind owns the seat and user session; Gamescope supplies Wayland/Xwayland.
# Exiting Steam returns to SDDM, where Plasma can be selected for desktop setup.
export XDG_CURRENT_DESKTOP=gamescope
exec gamescope --backend drm --steam --expose-wayland -- /usr/bin/bc250-steam-session --client
