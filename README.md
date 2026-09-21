# BC-250 living-room PC

A bootc image for an AMD BC-250 used as a Steam machine, Jellyfin client and
ad-free YouTube player. Version **0.2.0** starts directly from the official
`quay.io/fedora/fedora-bootc:44` image, pinned by digest in `Containerfile`.
It explicitly installs Fedora's kernel, Mesa, KDE Plasma, SDDM, Gamescope and
controller support, Steam from RPM Fusion, and the BC-250 SMU governor from
filippor's COPR. That COPR is restricted to the governor package. CPU/CU unlocks
remain opt-in. The earlier `0.1.0` images used Bazzite; use `0.2.0` for new installs.

This is an initial image, not yet validated on a physical BC-250. Assume the
Jellyfin server runs elsewhere. Hardware-dependent checks are listed below.

The repository follows the structure of `weyvalleyradio/ops/images/offair`:
explicit installation paths in a versioned `Containerfile`, top-level helper
scripts, and directories grouped by the service or subsystem they configure.

## Immutability

The OS, kernel, drivers, helper programs and default policies are shipped in the
bootc image. `/usr` is read-only on the installed system. Changes to that software
go through an image rebuild and a new deployment with rollback available; do not
use `rpm-ostree install`, `dnf` on the host, or `bootc usr-overlay` for normal use.

`/etc` remains writable for machine configuration, and `/var` (including home
directories) for accounts, Steam games, Flatpaks and Kodi data. Those are the
intentional mutable parts. Firmware and saved hardware settings are separate from
OS rollback. User Flatpaks and Kodi add-ons update independently of the OS image.

## Power management

CPU idle and frequency scaling require corrected ACPI tables on this board.
The default `ACPI_MODE=initramfs` build compiles the pinned
[6/8-core ACPI fix](https://github.com/e-tho/bc250-acpi-fix) and includes its tables
in the image's initramfs. This provides the idle-state definitions and the eight
800–3200 MHz P-states, without a per-machine `/boot` script or local initramfs
regeneration. Kernel, initramfs and ACPI fixes update and roll back together.

**Use only one ACPI provider.** With the default image, disable a modded BIOS's
ACPI injection. If the BIOS already provides the fixes and you want to use those,
build with `--build-arg ACPI_MODE=firmware` instead. That image leaves the base
initramfs intact. `cat /usr/share/bc250/acpi-mode` identifies the installed choice.

The default TuneD profile is `bc250-balanced`, using `schedutil` (or `ondemand`)
so CPU frequency follows load and boost remains available. CPU C-states are
allowed; disabling system suspend does not disable CPU idle states. The CPU is
not held at a fixed overclock or a permanent performance governor. KDE's balanced
power profile maps to this policy; power-saver and performance remain explicit
user choices. On an existing installation whose `/etc` settings have been changed,
select balanced again with `powerprofilesctl set balanced` after rebasing.

The GPU's separate SMU governor scales between **500 and 1500 MHz**, using the
supplied 700–900 mV operating points, allowing lower clocks during light loads.
The 1500 MHz ceiling is a conservative starting point for both 24 and 40 CUs;
frequency, voltage, temperatures and stability still need board testing. TuneD's
balanced profile leaves GPU control to that governor.

Verify after boot:

```sh
tuned-adm active
powerprofilesctl get
cpupower frequency-info
cpupower idle-info
cat /sys/devices/system/cpu/cpufreq/policy*/scaling_governor
cat /sys/devices/system/cpu/cpufreq/policy*/scaling_min_freq
cat /sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq
```

Check frequency at idle and under load, and increasing CPU idle-state residency.
If no cpufreq policies exist, the ACPI/kernel setup is incomplete; selecting a
power profile alone does not solve that. Measure wall power with the TV workload
as well as idle, since shared GDDR6 and the board's other components also consume
power. No blanket USB autosuspend or forced PCIe ASPM policy is applied to the
remote/DisplayPort path.

## What replaces the Shield?

| Use | Starting choice | Trade-off |
| --- | --- | --- |
| Games | Steam Big Picture / Gamescope / Proton | Dedicated session in SDDM; Fedora controller rules |
| Jellyfin on the TV | Kodi + Jellyfin for Kodi | Remote-friendly interface, libraries on Kodi's home screen |
| Multiple Jellyfin users/servers | Kodi + JellyCon instead | Browse the server without synchronizing Kodi's library |
| YouTube with a D-pad | Kodi's YouTube add-on + SponsorBlock service | Configure its API/login requirements and validate playback with the U2 |
| Ad-free YouTube with SponsorBlock | FreeTube, included by media setup | Desktop interface; a pointer is useful, subscriptions are local |

**Ad-free YouTube is a requirement.** FreeTube explicitly supports playback without
YouTube ads and includes SponsorBlock. Kodi is the preferred interface for the U2;
its YouTube add-on plus the separate
[SponsorBlock service](https://github.com/siku2/script.service.sponsorblock)
is the TV candidate to validate. SponsorBlock skips creator-inserted sponsor
segments using community timestamps; that is separate from avoiding YouTube's
pre-roll/mid-roll advertisements. Acceptance includes both, as well as browsing,
searching and playing using the remote. Merely launching a YouTube client does
not satisfy this requirement.

[SmartTube](https://github.com/yuliskov/SmartTube) targets Android, not native
Linux. Waydroid is an experiment we can explore if the exact app matters, but it
adds another layer to playback and input. It is not the default TV session here.
[FreeTube](https://github.com/FreeTubeApp/FreeTube) is included as the ad-free
desktop alternative while the full remote experience is validated.

The major hardware constraint is **video decoding**. Do not assume that this APU
has the video acceleration of an ordinary desktop Radeon. As checked on
2026-09-21, we have not found a confirmed working BC-250 VCN decoding configuration
to ship. [VCN enablement research](https://github.com/daveconde/bc250-vcn-enable)
identifies VCN 2.0.3 in the firmware's IP discovery data, but is still working on
power/reset sequencing and initialization. This is not evidence that decoding is
physically impossible, nor a ready BIOS toggle or driver setting.

The separate
[compute-video driver](https://github.com/simpmix/bc250-encoding-decoding-fix)
accelerates **encoding** using GPU compute and explicitly advertises no decode
entrypoints. Installing it does not enable accelerated Jellyfin/YouTube playback.
Unlocking 40 CUs also does not enable VCN. Plan on CPU decoding or transcoding on
the Jellyfin server until a decoder is demonstrated on this board. Test CPU use
and wall power during playback; a low idle power figure does not establish low
video-playback power. Validate high-bitrate 4K HEVC, VP9/AV1, subtitles,
HDR, audio passthrough, and frame pacing with your actual media before replacing
the Shield. Dolby Vision and Android streaming-app compatibility are not promised.

The board has DisplayPort. Select a DP-to-HDMI adapter for the actual TV mode and
audio formats required; test that entire path. CEC and wake from a remote should
not be assumed to work through an ordinary adapter.

## Build

On an x86-64 Linux builder with Podman:

```sh
sudo podman build --tag localhost/bc250:dev --file Containerfile .
```

Allow substantial disk space for the desktop/gaming packages and image layers.

The build runs `bootc container lint --fatal-warnings`. GitHub Actions builds pull requests and
`main`; CI publishing is an explicit workflow dispatch with `publish` enabled. It
publishes the `ARG IMAGE_VERSION` declared in `Containerfile`, currently
`ghcr.io/uhthomas/bc250:0.2.0`, and refuses to overwrite an existing version.
Select `acpi_mode=firmware` to build and publish `0.2.0-firmware` instead. Both
variants come from the same source; choose exactly one ACPI provider on the board.
Increment the version for each release. No image is published by a local build.
Locally built releases must pass the same lint and helper checks before push,
carry the source commit's `org.opencontainers.image.revision` label, and use a new
version tag. Record the registry digest returned by the push.

The CPU-helper tests mock PCI, SMU and service commands; installer tests exercise
rejection paths with bootc mocked. Run both inside the container without passing
through hardware:

```sh
sudo podman run --rm --network=none --entrypoint /usr/bin/python3 \
  --volume "$PWD/tests:/tests:ro" localhost/bc250:dev -m unittest discover -s /tests -v
```

The base pin fixes the Fedora bootc input. Additional RPMs resolve from Fedora,
RPM Fusion and the governor's COPR at build time, so the complete build is not
bit-for-bit reproducible. ACPI/CPU sources and the CU manager are pinned separately.
Update the base digest deliberately and repeat the hardware checks. Flatpaks,
Kodi add-ons, accounts, and saved CU settings live in persistent machine/user
state; an OS rollback does not roll those back.

## Install and update

Install this image directly from a **Fedora live USB booted in UEFI mode** using
rootful Podman and the image's `bc250-install` helper. Have Ethernet, a USB keyboard
and the TV/monitor connected. There is no preliminary Bazzite installation and no
default account/password. The install creates an unencrypted ext4 system and
injects your public SSH key for initial root access; secrets are not baked into
the image. A custom graphical installer ISO is not supplied.

The GHCR package has separate visibility from this public Git repository. After
the first push, open [the package settings](https://github.com/users/uhthomas/packages/container/bc250/settings)
and select **Change visibility → Public** to allow unauthenticated pulls. See
[GitHub's package visibility instructions](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility#configuring-visibility-of-packages-for-your-personal-account).
If the package has no connected repository, choose **Connect repository** on its
package page and select `uhthomas/bc250`. In package settings, enable **Inherit
access from repository** so the repository's GitHub Actions workflow can publish
future versions. The initial local push did not establish this connection
automatically, despite the image's source label.

Establish a working firmware baseline first. The community baseline uses a
modified BIOS with **512 MB dynamic VRAM** and **IOMMU disabled**; use the settings
appropriate to your firmware and verify the exposed system/GPU memory. See
[the BC-250 community prerequisites](https://github.com/62fixolab/Latest-Bazzite-AMD-BC-250-Patched-Images#install).

Select `0.2.0` when this image supplies ACPI fixes, or `0.2.0-firmware` when the
BIOS supplies them. Verify the BIOS setting first; an unknown configuration is
not evidence that ACPI injection is absent. For an exact tested deployment, replace
the tag with the published digest: `ghcr.io/uhthomas/bc250@sha256:<digest>`.

On the live USB, place your **public** SSH key(s), one per line, in
`/tmp/bc250-authorized_keys`. Install Podman if the live image does not include it:

```sh
sudo dnf install podman
lsblk -dp -o NAME,SIZE,MODEL,SERIAL
ssh-keygen -l -f /tmp/bc250-authorized_keys
```

Identify the destination by model, size and serial. **Installation erases the
entire selected disk.** Replace `/dev/disk/by-id/REPLACE_WITH_TARGET_DISK` below
with its actual whole-disk path. The helper refuses mounted disks/partitions and
asks you to type the resolved disk path before running bootc. Leave enough space
in the live environment's container storage to download and unpack the image.

```sh
BC250_IMAGE=ghcr.io/uhthomas/bc250:0.2.0
sudo podman run --rm -it --privileged --pid=host --ipc=host \
  --security-opt label=type:unconfined_t \
  --volume /var/lib/containers:/var/lib/containers \
  --volume /dev:/dev \
  --volume /tmp/bc250-authorized_keys:/run/bc250-authorized_keys:ro \
  --entrypoint /usr/sbin/bc250-install \
  "$BC250_IMAGE" /dev/disk/by-id/REPLACE_WITH_TARGET_DISK bc250 /run/bc250-authorized_keys
```

The bind mounts and privileges follow [bootc's installation instructions](https://bootc.dev/bootc/bootc-install.html).
After installation, shut down, remove the USB, and boot the installed disk. Find
its DHCP address, then connect from your workstation using the matching SSH key:

```sh
ssh root@<board-address>
```

Create your desktop administrator on the installed system. Replace `thomas` below
if you want another name; `passwd` prompts interactively:

```sh
useradd --create-home --groups wheel --shell /bin/bash thomas
passwd thomas
install -d -m 0700 -o thomas -g thomas /home/thomas/.ssh
install -m 0600 -o thomas -g thomas /root/.ssh/authorized_keys /home/thomas/.ssh/authorized_keys
restorecon -RF /home/thomas
```

SSH is enabled in the image. Verify login as your new user and `sudo` access before
testing display or GPU changes. Keep this on the local network; no router port
forwarding is needed. Log into **Plasma** on the TV for initial setup.

After the first boot, run `bc250-media-setup` as your desktop user. Establish a
working baseline for video/audio, ad-free YouTube, Steam, CPU frequency scaling
and wall power before applying CPU/CU unlocks. Test each unlock separately, then
together, using the acceptance checks below. Firmware experiments remain separate
from OS image updates and cannot be undone by `bootc rollback`.

Check `bootc status` after reboot. For updates from an existing bootc installation
without local RPM layering:

```sh
sudo bootc switch ghcr.io/uhthomas/bc250:0.2.0
sudo systemctl reboot
```

Use the firmware variant when appropriate. For a new release, use `sudo bootc switch` with
the new version (or its digest) and reboot. Published version tags are immutable,
so `bootc upgrade` on an existing version will not jump to another release.
`sudo bootc rollback` stages the previous deployment.
Choose the previous deployment in the boot menu if the new one cannot boot.
Do not add host RPM layers; change `Containerfile` and rebuild instead.
These initial publishing instructions do not configure image-signature verification.

Secure Boot and disk encryption are separate. The project assumes Secure Boot is
unavailable/disabled and chooses unencrypted storage for unattended couch startup.
[Linux dm-crypt/LUKS](https://www.kernel.org/doc/html/latest/admin-guide/device-mapper/dm-crypt.html)
can still provide passphrase-based encryption without Secure Boot or a TPM if the
requirements change. No MOK enrollment is needed for this setup.

## TV setup

In KDE Plasma, run as your normal user:

```sh
bc250-media-setup
```

This installs Kodi and FreeTube Flatpaks from Flathub using the network. They are deliberately
installed after deployment into the user's persistent storage, not `/var` inside
the build container. Rerunning setup preserves an existing remote keymap.

1. Open Kodi. In File manager, add `https://kodi.jellyfin.org` as a source.
2. In Add-ons, install `repository.jellyfin.kodi.zip` from that source, then install
   **Jellyfin for Kodi** from the new repository. Sign into your existing server.
   Use its default Add-on playback mode. For multiple accounts, consider JellyCon.
   Follow [Jellyfin's instructions](https://jellyfin.org/docs/general/clients/kodi/),
   including Kodi Sync Queue on the server when using Jellyfin for Kodi.
3. Install the YouTube add-on from Kodi's repository and follow its
   [API/login setup](https://github.com/anxdpanic/plugin.video.youtube/wiki/Personal-API-Keys).
   Install [siku2's repository and SponsorBlock service](https://github.com/siku2/script.service.sponsorblock#installation)
   and choose which sponsor categories to skip in its settings. This is a separate
   add-on; installing YouTube alone does not configure sponsor skipping.
   Keep account tokens and API credentials on the device, out of the image/repo.
4. In desktop Steam, add **Kodi** as a non-Steam game. If it is not listed, use
   `/usr/bin/flatpak` as the executable and `run tv.kodi.Kodi` as launch options.
   Do not enable a Proton compatibility tool for this native Linux application.
5. Log out of Plasma and select **Steam Big Picture** in SDDM's session selector.
   Kodi is a media entry in Steam; exiting Kodi returns to Steam.
   Establish controller and U2 keyboard navigation on the actual device before
   relying on this as the only living-room interface.

FreeTube is also installed for ad-free YouTube. Enable its SponsorBlock integration
in Settings to skip embedded sponsor segments. To add it to Steam, use
`/usr/bin/flatpak` with launch options `run io.freetubeapp.FreeTube`. Its desktop
interface may need a mouse/trackpad or a Steam Input pointer mapping; the U2's
D-pad alone is not yet a validated replacement for SmartTube navigation.

The Steam session runs Fedora's Gamescope and native Steam. Exiting Steam returns
to SDDM; select Plasma there for desktop setup. SteamOS-specific system settings
and Bazzite's session-switching helpers are not part of this image.

For unattended couch startup, after testing the session, create
`/etc/sddm.conf.d/80-bc250-autologin.conf` with your actual username:

```ini
[Autologin]
User=thomas
Session=bc250-steam.desktop
Relogin=false
```

This is machine-local configuration. Remove the file to return to the normal
login screen. No username or password is built into the public image.

## SofaBaton U2

Two useful paths:

* **Bluetooth LE:** use a USB adapter with confirmed Linux/BlueZ support for its
  exact chipset/revision. The [U2 supports BLE, not Bluetooth Classic](https://www.sofabaton.com/products/u2/compatibility/).
  In the SofaBaton app, choose a suitable Bluetooth keyboard/device profile and
  pair in KDE Bluetooth settings; mark it trusted. Test arrows, Enter, Back,
  play/pause and reconnect after reboot. A dongle's Bluetooth version alone does
  not guarantee that the U2 profile exposes the desired keys.
* **IR via FLIRC USB:** a predictable choice for Kodi keyboard mappings. Program
  an unused U2 IR device profile and teach FLIRC its buttons. The receiver presents
  keyboard input to Linux; configure it once with
  [FLIRC's software](https://flirc.tv/products/flirc-streacom).
  Place the receiver where it can see the remote. No Linux LIRC daemon is needed.

Keep TV/AVR power and volume assigned directly to those devices in the U2. Use a
gamepad for games. Sleep states are disabled in this image because
[BC-250 suspend/resume is unreliable](https://skillfishos.com/en/docs/hardware-bc250/).
Use shutdown/cold boot initially. Pairing/keyboard support does not imply remote
power-on from shutdown; that needs separate board/receiver testing.

Basic Kodi keys are arrows, Enter, Backspace, Space (pause), X (stop), C (context
menu), and I (information). The supplied optional FLIRC keymap adds:

| Key | Action |
| --- | --- |
| F1 | Kodi home |
| F2 | Jellyfin for Kodi add-on |
| F3 | YouTube add-on |
| F4 | Exit Kodi back to its launcher |

F2 assumes Jellyfin for Kodi, not JellyCon. The map is installed at
`~/.var/app/tv.kodi.Kodi/data/userdata/keymaps/bc250-remote.xml`; edit it to match
the profile you actually use. Inspect incoming remote keys with `sudo evtest`.

## 8 CPU cores: test in Linux, then consider firmware

The [original CPU unlock](https://github.com/rw-r-r-0644/bc250-core-unlock)
changes an SMU core mask. It takes effect after a warm reboot and is cleared by a
cold power cycle. It is not a normal supported BIOS setting.

Stop other SMU/overclock tools before testing. The helper checks for the BC-250
PCI ID, serializes invocations, temporarily stops the supplied governor, runs the
pinned upstream unlock, and restores the governor even if the unlock fails:

```sh
sudo bc250-cpu-unlock
sudo systemctl reboot
lscpu
stress-ng --cpu 0 --cpu-method all --verify --timeout 1h --metrics-brief
sudo journalctl -k -b
```

Expect 8 physical cores / 16 threads with SMT enabled. Look for machine-check
errors, incorrect results, crashes, and temperature problems. One stress test
does not prove every workload is stable. The upstream script refuses unexpected
factory masks; this helper does not expose its force option.

**For a validated board, firmware is the sensible permanent home for the CPU
unlock.** A DXE module performs it before OS enumeration, avoiding an extra Linux
boot after each power loss. The upstream project links
[RescueMei's BIOS modification](https://github.com/RescueMei/BC250-DXEv3-BIOSMOD).
Match the firmware revision and recovery procedure to the board, preserve its
original ROM, and account for the 8-core ACPI/fan changes. This image does not flash
firmware or arrange automatic CPU-unlock reboot loops. BIOS modifications cannot
be undone by `bootc rollback`. Until firmware is changed, rerun the helper and warm
reboot after each cold start to use all eight cores.

CPU unlocking can also affect GPU clock telemetry; validate the governor's
behavior and readings in the chosen firmware/kernel combination. Treat normal
operation at 6 cores as the fallback if either extra core is unreliable.

## 40 GPU CUs: keep it in the OS

The GPU's additional CUs are enabled through driver/register configuration after
GPU initialization. This is separate from the CPU unlock. The image includes
[the UMR-based live manager](https://github.com/WinnieLV/bc250-cu-live-manager)
through its hardware base, avoiding a locally patched `amdgpu` module tied to
every kernel build. It can restore the tested configuration on each boot.

Test without a game running. This image already supplies the conservative
500–1500 MHz GPU profile; 40 CUs require more power/cooling at a given frequency.
The profile is a starting point, not a guarantee for every board:

```sh
sudo bc250-cu-live-manager status
sudo bc250-cu-live-manager --dry-run enable all
sudo bc250-cu-live-manager enable all
```

Test real games and correctness/stability at temperature. Live dispatch changes
may leave Vulkan/driver topology reporting 24 CUs; inspect the manager's routed
CU state and actual workload behavior. Neither a displayed number nor a benchmark
speedup proves stability. See the community's
[40-CU testing guide](https://github.com/62fixolab/Latest-Bazzite-AMD-BC-250-Patched-Images/blob/main/docs/40cu.md).
Use 24 CUs or a smaller validated layout if necessary.

Only after the live configuration passes testing:

```sh
sudo bc250-cu-live-manager write-service-table
sudo systemctl enable bc250-cu-restore.service
```

The image's service uses the executable in `/usr` so tool updates follow OS
updates. Use this service instead of upstream `install-service`, which copies a
script into persistent `/usr/local`. The saved
table remains local at `/etc/bc250-cu-live-manager.conf`.

To return to stock GPU dispatch:

```sh
sudo systemctl disable bc250-cu-restore.service
sudo bc250-cu-live-manager stock-dispatch
```

If you already enabled the upstream service, also run
`sudo bc250-cu-live-manager uninstall-service`. Disabling either service alone does not revert live GPU
registers. For recovery from a failed saved configuration, append
`bc250.no-unlock` to the kernel command line in the boot menu for one boot, disable
the service, and retest. That flag only bypasses this repository's CU service;
it does not reverse a BIOS CPU unlock or an independently installed unlock service.

## Acceptance checks on the board

* Cold boot and warm reboot; correct CPU count and system/GPU memory split.
* Governor operating, GPU clocks scaling, and cooling/noise acceptable at idle
  and under a combined CPU/GPU load.
* Stock baseline games, then separately CPU unlock, GPU unlock, and both together.
* Representative Jellyfin and YouTube playback, including the hardest codecs,
  subtitles, resolution/frame rate, audio and display modes you use.
* YouTube without pre-roll/mid-roll ads, SponsorBlock skipping on a video with
  known segments, and search/subscriptions/playback using the intended remote.
* U2 navigation in Kodi and Steam, volume/power routing, and Bluetooth reconnect.
* OS upgrade/rollback and recovery with a saved CU configuration present.

Useful diagnostics: `bootc status`, `lscpu`, `lspci -nnk`, `vainfo`,
`systemctl status cyan-skillfish-governor-smu`, and `sudo journalctl -k -b`.
`vainfo` failure/no usable decode profiles is consistent with the video limitation;
do not interpret GPU rendering support as proof of video decoding support.
Any proposed VA-API decoding fix needs the relevant codec's `VAEntrypointVLD`
profile and a successful hardware-decoded playback test in the actual client.
`VAEntrypointEncSlice` only demonstrates an encoding entrypoint. A host driver
also needs to be available to a Flatpak client's runtime; host `vainfo` alone is
not sufficient.
