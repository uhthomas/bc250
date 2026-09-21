ARG IMAGE_VERSION=0.1.0

FROM registry.fedoraproject.org/fedora:44 AS acpi-build

RUN dnf5 --assumeyes --setopt=install_weak_deps=False install acpica-tools cpio make
COPY vendor/acpi-fix/ /src/
RUN make -C /src

# Bazzite Steam/Game Mode with the BC-250 governor and optional CU tools.
# Update the digest deliberately after testing on the board.
FROM ghcr.io/62fixolab/bazzite-bc250-patched-deck-40cu:latest@sha256:0e2f4ce77acd1cf2fbe73fcfd5f6f867386ba0ad9b4371099b57151821d2dff4

ARG IMAGE_VERSION
# Use firmware when a BIOS mod already supplies the CPU ACPI fixes.
ARG ACPI_MODE=initramfs

LABEL org.opencontainers.image.title="BC-250 Living-room PC" \
      org.opencontainers.image.description="Bazzite bootc image for Steam, Jellyfin and YouTube" \
      org.opencontainers.image.source="https://github.com/uhthomas/bc250" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      containers.bootc="1"

RUN dnf5 --assumeyes --setopt=install_weak_deps=False install \
        evtest \
        libva-utils \
        stress-ng \
    && dnf5 clean all \
    && rm -rf /run/dnf /var/cache/dnf /var/cache/libdnf5 /var/lib/dnf /var/log/dnf5.log

COPY media-setup.sh /usr/bin/bc250-media-setup
COPY cpu-unlock.sh /usr/bin/bc250-cpu-unlock
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

RUN chmod 0755 /usr/bin/bc250-media-setup /usr/bin/bc250-cpu-unlock \
    && command -v bootc \
    && command -v flatpak \
    && command -v python3 \
    && command -v lspci \
    && command -v umr \
    && command -v bc250-cu-live-manager \
    && command -v gamescope \
    && command -v steam \
    && rpm -q cyan-skillfish-governor-smu bluez tuned tuned-ppd kernel-tools \
    && systemctl enable bluetooth.service cyan-skillfish-governor-smu.service tuned.service tuned-ppd.service \
    && test "$(systemctl is-enabled bc250-cu-restore.service)" = disabled \
    && bash /tmp/bc250-acpi-image.sh "${ACPI_MODE}" \
    && rm /tmp/bc250-acpi-image.sh \
    && bootc container lint --fatal-warnings
