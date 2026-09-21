#!/usr/bin/env bash
set -euo pipefail

if (( $# > 1 )) || [[ -n "${1:-}" && "$1" != --with-freetube ]]; then
    echo 'Usage: bc250-media-setup' >&2
    exit 2
fi
# Keep the original --with-freetube invocation working; ad-free YouTube is now
# part of the default setup.
apps=(tv.kodi.Kodi io.freetubeapp.FreeTube)

if (( EUID == 0 )); then
    echo 'Run this as your desktop user, without sudo.' >&2
    exit 1
fi

# Flatpaks belong in persistent user storage, not in /var during an OCI build.
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install --user --assumeyes --noninteractive flathub "${apps[@]}"

kodi_userdata="$HOME/.var/app/tv.kodi.Kodi/data/userdata"
mkdir -p "$kodi_userdata/keymaps"
keymap="$kodi_userdata/keymaps/bc250-remote.xml"
if [[ ! -e "$keymap" ]]; then
    install -m 0644 /usr/share/bc250/kodi/remote.xml "$keymap"
fi

cat <<'EOF'
Kodi and FreeTube are installed. Launch them from the desktop or add them as
non-Steam games. FreeTube provides ad-free YouTube; enable SponsorBlock in its
settings to also skip sponsor segments inside videos.
In Kodi's File manager, add https://kodi.jellyfin.org as a source, then install
repository.jellyfin.kodi.zip and the Jellyfin for Kodi or JellyCon add-on.
For YouTube with the remote, see the repository README for Kodi's YouTube and
SponsorBlock add-ons, remote pairing, and Game Mode setup.
EOF
