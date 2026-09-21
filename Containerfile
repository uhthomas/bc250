ARG IMAGE_VERSION=0.2.0

FROM registry.fedoraproject.org/fedora:44 AS acpi-build

RUN dnf5 --assumeyes --setopt=install_weak_deps=False install acpica-tools cpio make
COPY vendor/acpi-fix/ /src/
RUN make -C /src

# Official Fedora bootc, pinned to the tested x86-64 manifest.
FROM quay.io/fedora/fedora-bootc:44@sha256:2e1c2bbd87411f2c6d90271bf2c51bf036c9cc4605cededbc56b2a9d998d1271

ARG IMAGE_VERSION
# Use firmware when a BIOS mod already supplies the CPU ACPI fixes.
ARG ACPI_MODE=initramfs

LABEL org.opencontainers.image.title="BC-250 Living-room PC" \
      org.opencontainers.image.description="Fedora bootc image for Steam, Jellyfin and ad-free YouTube" \
      org.opencontainers.image.source="https://github.com/uhthomas/bc250" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      containers.bootc="1"

COPY repos.d/ /etc/yum.repos.d/

# Steam is supplied by RPM Fusion. Pin its repository bootstrap packages, then
# let DNF verify application RPM signatures against the installed repository keys.
RUN curl -fsSL https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-44.noarch.rpm -o /tmp/rpmfusion-free.rpm \
    && curl -fsSL https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-44.noarch.rpm -o /tmp/rpmfusion-nonfree.rpm \
    && echo '8af2dbb02e3a72f0961ec79cf1ea3f350719cb830b0f99f59e939389feb34b1c  /tmp/rpmfusion-free.rpm' | sha256sum -c - \
    && echo 'c2606f494b0c4417bf6632f865448da3febb420e19182e47874d8db4c35a8a8e  /tmp/rpmfusion-nonfree.rpm' | sha256sum -c - \
    && dnf5 --assumeyes install /tmp/rpmfusion-free.rpm /tmp/rpmfusion-nonfree.rpm \
    && rm /tmp/rpmfusion-free.rpm /tmp/rpmfusion-nonfree.rpm

RUN dnf5 --assumeyes --setopt=install_weak_deps=False install \
        NetworkManager-wifi \
        alsa-utils \
        bluedevil \
        bluez \
        cyan-skillfish-governor-smu \
        dolphin \
        evtest \
        firewalld \
        flatpak \
        gamescope \
        kde-settings-sddm \
        kernel-tools \
        konsole \
        libva-utils \
        mesa-dri-drivers \
        mesa-vulkan-drivers \
        openssh-server \
        passwd \
        pciutils \
        pipewire \
        pipewire-alsa \
        pipewire-pulseaudio \
        plasma-desktop \
        plasma-nm \
        plasma-workspace \
        sddm \
        sddm-wayland-plasma \
        steam \
        steam-devices \
        stress-ng \
        sudo \
        tuned \
        tuned-ppd \
        umr \
        vulkan-tools \
        wireplumber \
        xdg-desktop-portal-kde \
        xdg-user-dirs \
        zram-generator-defaults \
    && dnf5 clean all \
    && rm -rf /run/dnf /var/cache/dnf /var/cache/libdnf5 /var/lib/dnf /var/log/dnf5.log

# This tool is standalone; no Bazzite base or kernel fork is required.
RUN curl -fsSL https://raw.githubusercontent.com/WinnieLV/bc250-cu-live-manager/a929085d791f126ce76a60eb609610820fb08066/bc250-cu-live-manager.sh -o /usr/bin/bc250-cu-live-manager \
    && echo '304d0b51838ec4ffc80c56894c4867a04523bf1ba27e51f662cbfc79616e442d  /usr/bin/bc250-cu-live-manager' | sha256sum -c - \
    && chmod 0755 /usr/bin/bc250-cu-live-manager

COPY media-setup.sh /usr/bin/bc250-media-setup
COPY cpu-unlock.sh /usr/bin/bc250-cpu-unlock
COPY install.sh /usr/sbin/bc250-install
COPY steam-session.sh /usr/bin/bc250-steam-session
COPY wayland-sessions/ /usr/share/wayland-sessions/
COPY bootc/ /usr/lib/bootc/install/
COPY kodi/ /usr/share/bc250/kodi/
COPY vendor/ /usr/share/bc250/vendor/
COPY --from=acpi-build /src/SSDT-CPU.aml /src/SSDT-PST.aml /src/SSDT-STUBS.aml /usr/share/bc250/acpi/
COPY acpi-image.sh /tmp/bc250-acpi-image.sh
COPY dracut.conf.d/ /usr/lib/dracut/dracut.conf.d/
COPY kargs.d/ /usr/lib/bootc/kargs.d/
COPY modules-load.d/ /usr/lib/modules-load.d/
COPY tuned/bc250-balanced/ /usr/lib/tuned/profiles/bc250-balanced/
COPY tuned/ppd.conf tuned/active_profile tuned/profile_mode /etc/tuned/
COPY governor/config.toml /etc/cyan-skillfish-governor-smu/config.toml
COPY sleep.conf.d/ /usr/lib/systemd/sleep.conf.d/
COPY systemd/ /usr/lib/systemd/system/
COPY tmpfiles.d/ /usr/lib/tmpfiles.d/

RUN chmod 0755 /usr/bin/bc250-media-setup /usr/bin/bc250-cpu-unlock /usr/sbin/bc250-install /usr/bin/bc250-steam-session \
    && command -v bootc \
    && command -v flatpak \
    && command -v python3 \
    && command -v lspci \
    && command -v umr \
    && command -v bc250-cu-live-manager \
    && command -v gamescope \
    && command -v steam \
    && command -v dbus-update-activation-environment \
    && rpm -q cyan-skillfish-governor-smu bluez tuned tuned-ppd kernel-tools \
        mesa-dri-drivers.i686 mesa-vulkan-drivers.i686 vulkan-loader.i686 \
    && systemctl enable bluetooth.service cyan-skillfish-governor-smu.service tuned.service tuned-ppd.service \
        NetworkManager.service firewalld.service sshd.service sddm.service \
    && systemctl --global enable pipewire.socket pipewire-pulse.socket wireplumber.service \
    && systemctl set-default graphical.target \
    && test "$(systemctl is-enabled bc250-cu-restore.service)" = disabled \
    && bash /tmp/bc250-acpi-image.sh "${ACPI_MODE}" \
    && rm /tmp/bc250-acpi-image.sh \
    && mv /var/lib/authselect/checksum /etc/authselect/checksum \
    && ln -s /etc/authselect/checksum /var/lib/authselect/checksum \
    && authselect check \
    && rm -rf /run/sddm /run/selinux-policy /run/setrans /run/tuned \
        /var/cache/libX11 /var/cache/swcatalog /var/cache/ldconfig \
        /var/log/dnf5.log* \
    && bootc container lint --fatal-warnings
