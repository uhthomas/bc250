# BC250 Pico 2 implementation

**Current board state, 2026-09-29 after delayed VCN diagnostics:** Signed
RAM-only pre-map hooks confirmed that all sixteen PSP-visible VCPU cache
window words and all three MPC muxes retained their full 32-bit programmed
values across one full VCPU wait, before any second-call replay. Separate
delayed reads found the PSP soft-reset low 28 bits still zero and the MPC
replacement-mode low 28 bits at `0x10`.
An attempted PSP read mapping of the firmware TMR and a matched
bookkeeping-address control both returned low 28 result bits `0xf`, so
that probe cannot establish whether firmware bytes reached the VCPU.
VCPU-ready remained absent and no frame decoded;
`CC_UVD_HARVESTING=3` is an availability clue, not a proven start command.
BC250 is on normal Fedora boot
`e8d08497-33f8-4f87-befb-d26a04cd0d98` with `amdgpu` bound, `/boot`
read-only and no diagnostic GRUB entry. Pico CS-PASS v2 is armed in SRAM,
the Pi recovery timer is stopped, and neither BIOS EEPROM nor Pico QSPI
was written. See [the investigation](../../docs/video-decode-next-step.md).

**Earlier combined policy trial, 2026-09-29:** An early Trusted-OS client-12
`SEC_GASKET` replay latched the descriptor readback, but a combined early
and late policy VCN trial still left powered VCN harvest at `3`, host
firmware-cache/reset reads at `ffffffff`, VCPU PC at zero and the decode
ring timed out. The Pico verified 1,558/1,558 RAM-only substitutions with
zero faults across two firmware passes. The board has been returned to
CS-PASS v2 in Pico SRAM and normal Fedora boot
`2913c705-d2be-451f-bc7b-700bf057c4f3`, with `amdgpu` bound and the Pi
PDU timer stopped. See [the investigation](../../docs/video-decode-next-step.md).
No BIOS EEPROM or Pico QSPI flash was written; no decoded frame exists.

**Earlier retarget cross-check, 2026-09-28:** With the first signed
`SEC_GASKET` tuple redirected from
`0x1f820 <- 0x185103` to `0x1f81c <- 0` in Pico RAM, the ABL0 policy read
hook measured `0x1f820=0` on both boot passes. The Pico verified 1,398/1,398
substitutions, fault 0, and Fedora booted normally as
`2c11882a-1254-4608-b325-a4d2092a71fd`. The corresponding harvest-read
trial still measured `CC_UVD_HARVESTING=3`, and VA-API still fails. This
narrows the early policy effect but does not identify the harvest source.
The Pi 5 was restarted after the capture at the user's request; the Pico
returned to passive mode and CS-PASS v2 was loaded into RAM and armed. The
BC250 remained running. See [the investigation](../../docs/video-decode-next-step.md).
No BIOS EEPROM or Pico QSPI was written.

**Earlier VCN investigation, 2026-09-28:** The Pi 5 was restarted and
the Pico recovered. A RAM-only first-read substitution of the signed
`SEC_GASKET` policy value `0x1f820 <- 0x185103` changed ABL0's readback to
zero while leaving the policy signature and verification read stock. Fedora
booted. The same method changed the adjacent `0x1f8a4` value to zero, but
`CC_UVD_HARVESTING` stayed `3` at ABL0 when either value or both values were
zero. Retargeting the early tuple to `0x1f81c <- 0` also left harvest at `3`.
The pinned `--set-1f8a4-f` option instead applies the Steam Deck's single
different bit on the first BC250 read. ABL0 accepted `0xf`, but the paired
readback still measured `CC_UVD_HARVESTING=3`; see
[`video-decode-next-step.md`](../../docs/video-decode-next-step.md).
An authenticated Deck/Cezanne hybrid then changed seven early gasket rows,
added two Deck rows, and retained the four Cezanne windows needed for the
BC250 VCN aperture. It booted and verified every Pico substitution, but VCPU
still did not report ready. The [generator](prepare_deck_gasket_hybrid.py)
and [evidence](../../docs/video-decode-next-step.md) record that RAM-only trial.
The current Pico image is the RAM-only
`policy-first-read-1f81c-zero-harvest` profile; it completed both boot passes
with 1,398/1,398 substitutions, fault 0, and Fedora is running on boot
`f9a9e050-19a0-407f-989c-afa13fd33cfa`. VA-API still fails; no VCN frame
has decoded. See [the investigation](../../docs/video-decode-next-step.md).
No BIOS EEPROM or Pico QSPI payload was written.

**Earlier ABL fabric investigation, 2026-09-28:** RAM-only signed hooks measured
PSP-aperture `0x50d6c` low 16 bits as `0xc0` at ABL0–ABL3 entry and `0xf0`
at ABL3 exit. Full-value guarded bit-11 writes at ABL3 entry and exit read
back the original values (`0xc0` and `0xf0`) immediately. Both trials
completed two Pico passes with all substitutions verified, zero faults and
healthy Fedora boots. That Pico image was the RAM-only
`abl3-entry-fabric-toggle-entry` profile, armed with MISO input-only between
reads. The actual VCN harvest value was already `3` at ABL0 entry; these
fabric observations do not establish its cause. VA-API still fails and no
frame has been decoded. See [the investigation](../../docs/video-decode-next-step.md).
Neither BIOS EEPROM nor Pico QSPI payload was written.

**Earlier ABL0 result, 2026-09-28:** The signed RAM-only ABL0-entry
[read hook](abl0-entry-harvest.S) measured `CC_UVD_HARVESTING=3` on both
boot passes. A separate [guarded write hook](abl0-entry-harvest-clear.S)
required that exact full register value, wrote volatile zero through the
PSP SMN aperture, and read back `3` on both passes. The Pico verified all
1,396 substitutions without fault; Fedora is running on boot
`3e02c592-beaa-437d-93ef-ac8b06ee3fe4`. This test rules out the attempted ABL0 write path, but does
not establish whether the value comes from an earlier stage, a hardware
latch or a fuse. No BIOS EEPROM or Pico QSPI payload was written, and no
VCN-decoded frame exists. See [the investigation](../../docs/video-decode-next-step.md).

**VCN fabric timing, 2026-09-28:** A first-TOS read measured `0x50d6c=f0`
and `CC_UVD_HARVESTING=3`, while a core-mask control was `0x77` then `0xff`
on the same boot. A guarded RAM-only write of `0x8f0` to `0x50d6c` read back
`f0`; the hook restored/verified `f0`, and Fedora booted. See
[the investigation](../../docs/video-decode-next-step.md). No BIOS or Pico
QSPI payload was written.

**Pi 5 recovery, 2026-09-28:** Rebooting the Pi restored its USB controller
while the BC250 remained running. The Pico then enumerated on `/dev/ttyACM0`
in its QSPI `BC250-PICO2-PASSIVE v1` image with all outputs off. Because the
BIOS chip's CS# leg is lifted, restore and arm the RAM-only CS relay with
`python3 /home/pi/load_and_arm_cs_pass.py --uf2 /home/pi/bc250_cs_pass_v02.uf2`
before any BC250 cold boot. The observed post-arm status was
`BC250-PICO2-CS-PASS v2 armed=1 gate=1 host_cs=1 miso=INPUT`; the same Fedora
boot stayed healthy. A Pi restart alone does not leave the next BC250 boot
ready.

**Earlier VCN policy result, 2026-09-28:** The first-TOS direct-aperture read found
`0x1f820=0x185103`, `0x1f8a4=0xb` and `CC_UVD_HARVESTING (0x1f81c)=3`.
A guarded RAM-only hook temporarily cleared both policy words and read them
back as zero, yet a zero write to harvest still read back `3`. It restored
the policy words, and Fedora booted with every Pico substitution verified.
An earlier core-mask control changed from `0x77` at TOS entry to `0xff` after
boot, validating that the aperture was live. The [marked IPL slice hook](tos-entry-ipl-slice.S)
now distinguishes its encoded reads from ordinary BIOS reads. Two bounded
8 KiB reads reached Fedora and identify `0x54000..0x58fff` as AGESA ABL
material, not the earlier PSP bootloader. The Pi 5 was restarted and the Pico
returned to RAM-only CS-PASS v2. Details are in
[the VCN investigation](../../docs/video-decode-next-step.md). No BIOS or
Pico QSPI payload write, and no decoded frame.

**Earlier DF-lock result, 2026-09-28:** The [early-CS-release selector](burst_match_early_od.pio)
served both full 20,727-read UEFI passes from an exact-original QSPI control
and booted Fedora. Its final [DF-lock stream candidate](df_lock_stream_control.c)
trial also completed both passes (41,454/41,454 reads, `fault=0`, maximum
rearm 162 Pico cycles). The 1,327,104-byte candidate payload was independently
read back from Pico QSPI; one input-only 64-byte second-pass MISO sample
matched all expected words. Fedora booted, but AMDGPU detected no VCN block
and VA-API could not initialize. Post-boot root-SMN `0x50d6c` remained `0xf0`.
The candidate is not a hardware-decoding fix and must not be written to BIOS.
The Pi 5 restart recovered Pico USB during restoration; the known CS-PASS v2
RAM image is armed with MISO input-only, and original-BIOS Fedora is healthy
on boot `f695bd15-ce10-4b19-98b8-4fd3b37ca543`. The BIOS EEPROM was not
written. The older late-release selector's one-pass failure is described in
[the full note](../../docs/df-lock-control-20260928.md).

**Earlier consecutive original-byte control, 2026-09-28:** The RAM-only
[on-chip rearm bench](burst_rearm_bench.c) returned all 16,384 words of 1,024
sequential 64-byte reads from uncached Pico flash at 34 MHz and a separately
measured 1,070 ns CS# high gap; core1 rearm took at most 52 Pico cycles.
The [board control](burst_sequence_control.c), using 16 private original-ROM
replies generated by [this pinned generator](prepare_original_burst_sequence.py),
then completed **16/16** handoffs during each of two separately armed BC250
PDU boots. Fault, DMA remainder and FIFO remainder were zero; longest rearms
were 133 and 137 cycles, and Fedora returned after both. An intervening boot
used only the control's original-flash fallback.
No Pico or BIOS flash write occurred. See [the full note](../../docs/df-lock-control-20260928.md).

**Earlier onboard-flash source and BC250 burst gap, 2026-09-28:** The RAM-only
[XIP self-benchmark](burst_xip_bench.c) served and captured 1,000/1,000
nonzero 64-byte replies from the Pico's uncached onboard flash at an actual
34 MHz. An earlier apparent 42.5 MHz pass compared zero-filled data because
the RAM image had not initialized QMI/XIP; the corrected 42.5 MHz run failed
on its first word. The bench used only unwired GP8–GP12 and left the
board's GP7 original-flash relay active. The RAM-only
[CS# gap counter](cs_gap_timing.c) then measured all 21,610 internal gaps of
the first contiguous UEFI 64-byte-read pass during a passive PDU boot:
minimum ~1.071 µs, median ~1.076 µs, maximum ~1.106 µs. No MISO drive,
BIOS EEPROM write or Pico flash write occurred; Fedora returned. The
later multi-burst selector was built and tested as reported above. See
[the timing note](../../docs/df-lock-control-20260928.md).

**64-byte active handoff, 2026-09-28:** The RAM-only
[address-matching selector](burst_match_late_od.pio) and
[control](burst_match_control.c) substituted an **exact-original** 64-byte
reply at `READ03 0xae0140`. Its passive and active trials both booted Fedora;
PIO completion reported one verified handoff, no fault and empty DMA/FIFO.
The first-target snapshot recorded original-flash CS# released and Pico MISO
enabled. A fresh lossless command trace showed that the preceding `0xae00c0`
read is optional, explaining the failure of the earlier fixed-skip selector.
At that stage, the first DF-lock candidate required 1,386,944 changed reply
bytes and could not fit in Pico SRAM. The later equal-length candidate was
tested as reported above. See [the full note](../../docs/df-lock-control-20260928.md).
No BIOS EEPROM or Pico flash was written in that earlier handoff trial.

**UEFI DF-lock candidate, 2026-09-28:** The unflashed offline control in
[the DF-lock investigation](../../docs/df-lock-control-20260928.md) changes a
compressed UEFI firmware volume. The BC250 reads that ~1.38 MiB SPI region
in 64-byte bursts. The older sparse interposer serves only one four-byte
word per verified transaction, so it cannot safely apply the UEFI candidate.
A RAM-only [input-only capture](cs_pass_burst_snapshot.c) measured one
64-byte original-flash reply at ~33.34 MHz, all bytes matching the clean ROM,
with Fedora booting afterwards. Neither SPI flash was written.

**SMN alias control, 2026-09-28:** The RAM-only first-VCN read of PSP service
argument `0x5a870` returned `0xff`; the host root-SMN bridge read the same
`0xff` both before and after. Fabric argument `0x50d6c` separately matched
the host at `0xf0`. The Pico verified 770/770 substitutions in the new boot.
This strengthens the PSP/host alias model without identifying the physical
source of the VCN disable state. Details are in
[the VCN investigation](../../docs/video-decode-next-step.md).

**Early PSP fabric result, 2026-09-28:** The RAM-only Pico captured a
`0x50d6c` PSP read of `0xf0` at the first VCN request. A second guarded
profile requested `0x8f0`, read back the unchanged `0xf0`, then verified the
original value after restoration. Both boot passes of each profile had zero
Pico faults. See [the VCN investigation](../../docs/video-decode-next-step.md).

**Current VCN result, 2026-09-28:** A RAM-only profile omitted both the
native type-13 and earlier signed `SEC_GASKET` policy requests to write
`0x185103` to `0x1f820`; the policy object itself stayed byte-identical.
The Pico verified 1,458/1,458 substitutions over two boot passes with no
routing fault. Powered host MMIO still read `CC_UVD_HARVESTING=3`, and the
VCN decode ring timed out. The policy-loop omission was verified offline but
not observed with a direct live marker. The source of those disable bits
remains unknown; see
[the latest VCN evidence](../../docs/video-decode-next-step.md).
When replacing the RAM-only Pico image on this wired board, use
[`load_and_arm_ram.py`](load_and_arm_ram.py) while the BC250 is already
running and host CS# is idle high; then cold-cycle the BC250. With board power
off, the CS# sense line reads low and the loader deliberately refuses to arm.

**Current board result, 2026-09-27:** The [six-wire Pico 2 connection](../../docs/pico2-six-wire-miso.md)
boots Fedora through the original BIOS flash in pass-through mode. After
correcting the selector's MISO edge timing, exact-original active replies
also booted. The [type-51 key trial](../../docs/pico2-type51-vcn-trial.md)
injected the authentic VCN2 usage-6 record during the copy read, booted
Fedora and changed a bounded live PSP authentication control to the predicted
post-key bounds error. The unmodified VCN firmware request now fails later
with `0x80000029`; VCN MMIO and hardware decode remain unavailable. The board
is restored to working pass-through mode, with Pico MISO disabled. No BIOS or
Pico flash write was made for these trials.

Earlier [five-wire address hunts](../../docs/pico2-cs-pass-hunt.md) yielded
two matching filtered 1,856-hit sequences. The later
[RLE full-command capture](../../docs/pico2-full-boot-trace.md) losslessly
recorded 1,832,116 commands and showed two passes matching through the last
changed word. These captures generated the sparse profile used by the board
controls.

Two Pico 2 UF2 images and their host tools are prepared. The passive v0.2 image
has booted on the physical Pico and passed its full 393,248-byte USB pattern/CRC
test after correcting the first capture's buffering bug. Two passive reboot
captures now show the same 2,133 complete reads, all matching the ROM, at about
**33.27 MHz SPI**. The passive Pico ran at **150 MHz**. The current interceptor fails
the measured timing, including an offline 480 MHz replay; see the
[measurement report](../../docs/pico2-measured-timing.md). It remains locally
tested only. Start with the
[wiring guide](../../docs/pico2-wiring.md), which includes passive, isolated
bench and later CS#-switch connections.

The Pico will be hosted by the Pi 5. The [Pi quick-start](../../docs/pico2-pi-start.md)
uses its installed ARM64 picotool and included working-ROM reference, so
flashing, capture collection and initial decoding can all run on the Pi.

An optional passive v0.3 address-hunt candidate is staged separately under
`output/pico2/candidates/hunt-v03/` and on the Pi in the same relative path.
It has been built, checked against recorded edges, flashed and USB-tested
with all GPIO leads removed. It then measured the key, TOS and driver read
locations with the five passive wires attached. Four raw windows cover all
318 changed four-byte words at least once, each with the working-ROM reply.
The main two-image kit still contains the previous tested passive v0.2.
The [measurement report](../../docs/pico2-measured-timing.md) records this
candidate and the isolated 200/480 MHz reply models. Neither is an active board
interceptor.

A separate `output/pico2/candidates/fast-bench-v01/` image is linked into
RP2350 **RAM**, so `picotool load -v -x` can execute it without another Pico
flash write. It runs the preselected reply PIO at an experimental 200 MHz on
the isolated Pi 5 SPI0 bench only. Its [bench guide](../../docs/pico2-fast-bench.md)
requires every BC250 lead removed and the BIOS chip left untouched. The image
was loaded and verified in Pico RAM on 2026-09-26. After the user corrected
the jumper orientation, it returned all 128 words correctly at requested Pi
SPI speeds of 1, 5, 10, 20 and 33 MHz, and all 1,024 words at requested
33 MHz. DMA completed in every passing run. These are isolated Pi functional
checks, not an analogue BC250 timing qualification.

The `output/pico2/candidates/select-bench-v01/` image combines the
preselected PASS/PATCH route and reply in one 30-instruction PIO state machine.
It has passed modeled 200 MHz replay around five measured read windows and
the 48 local tests. On the isolated Pi, v0.1 passed mixed routing and replies
through requested 20 MHz, but the GP6 first-clock observer found intermittent
route errors at requested 33 MHz while all PATCH replies remained correct.
The `select-bench-v02/` RAM-only diagnostic sampled GP6 on the first and
second clocks. At requested 33 MHz the failures were PASS rows, with GP6
high on both sampled clocks; a 1,024-read run failed on 229 PASS rows despite
a requested 1 ms extra gap. The `select-bench-v03/` candidate preselects PASS
while host CS# is idle. Its 32-instruction PIO passed 48 local tests and 50
measured-edge replay cases. The physical v0.3 run still failed on 14 PASS
rows in a requested 33 MHz run. `select-bench-v04/` keeps that selector but
adds an idle USB peek of the GP6 pad and PIO output latch. Its 1,024-read
physical run at requested 33 MHz found 225 PASS rows where PIO reported
output-low/enable-high but the GP6 pad stayed high; a 1,024-read 20 MHz run
passed. A RAM-only `select-bench-v05/` candidate reads GPIO6's function mux,
final output-to-pad, output-enable-to-pad and pad configuration.
The user measured GP6→3V3 open and GP6→GND as 473 Ω on the 2 kΩ range.
The v0.5 candidate was subsequently loaded into Pico SRAM. Its 100 kHz and
20 MHz controls passed, but 244 PASS rows failed in a 1,024-read requested
33 MHz run, starting at row 51. The PIO output and final `OUTTOPAD` were low,
output enable was on, and the pad input remained high. The GPIO mux and
override registers were normal. A same-selector GP7/pin-10 comparison is
built and staged on the Pi at `select-bench-gp7-v05/`. It passed the same
1,024-read requested-33-MHz run with zero route, idle-pad or PATCH-reply
errors. That supported moving the flash-CS output to GP7; this earlier
isolated interceptor still used GP6 and was not board-ready.
An isolated v0.6 GP7 candidate adds a PIO1/DMA capture of each 32-bit SPI
command for **post-run** comparison with the Pi script. It is staged at
`select-commands-gp7-v06/`; it cannot reject a wrong command before the
current transaction drives data, and it has no board-arm command.
It has now passed the 1,024-read requested-33-MHz isolated run with every
command, route and PATCH reply correct. An injected one-bit address error was
reported on the exact row in a separate low-speed negative control. A
real-time fault path and complete board profile were still missing at that
stage.
All candidates use the same five isolated Pi jumpers
with **GP6 / Pico pin 9 entirely unconnected**; the GP7 comparison also
requires **GP7 / Pico pin 10 entirely unconnected**.
Those isolated-bench candidates lacked a BC250 board-arm command. The
[measurement report](../../docs/pico2-measured-timing.md) records the results
and limits.

| Artifact | Purpose | BC250 connection |
|---|---|---|
| `bc250_passive.uf2` | Input-only four-channel raw capture, USB transfer with CRC32 | Five passive wires; BIOS chip untouched |
| `bc250_interceptor.uf2` | Command/address-checked CS routing and SRAM replies; real signed words in a synthetic replay | **None**; isolated Pi 5 only; keep GP6 disconnected |
| Private `overlay.bin` | Original/patched type-50 database and signed TOS/driver segments | Not a firmware/UF2; board timing/profile not ready |

Pin contract: GP2=host CS#, GP3=SCLK, GP4=MOSI, GP5=MISO. The passive image
leaves GP6 and GP7 as inputs. The older isolated interceptor drives GP6 only
after `arm-isolated`; the current board selector uses GP7 for the isolated
flash CS# leg. UART
stdio is disabled. The passive build forces output enable off on GP2–GP6
and has no PIO output instructions. Its default clock is the stock 150 MHz.

## Verify USB transfer before connecting GPIO

Passive v0.2 fixes mixed libc/SDK output buffering that could leave a capture's
last binary bytes unsent. It uses direct SDK output for headers, data and the
trailer, with newline translation disabled. After flashing over USB, leave
GPIO disconnected and run on the Pi:

```sh
python3 capture.py usb-test --port /dev/ttyACM0 --output captures/usb-selftest-v02.bcraw
```

This transfers the full 393,248-byte packet and checks every payload byte plus
its CRC. It touches no SPI pins. The synthetic flag `0x80000000` prevents it
from being accepted as a board capture. Status includes `transport=direct` and
`usb_test=1`. Failed USB transfers now preserve received bytes in a `.partial`
file for diagnosis, rather than losing all data.

## First passive capture

Hold BOOTSEL while connecting the **unwired** Pico by USB and copy
`bc250_passive.uf2` onto its `RP2350` drive. After reboot, use the actual
`/dev/serial/by-id/...` USB serial path (`ls /dev/serial/by-id/`). Make the five
passive connections in the guide with both devices unplugged, power the Pico,
then run on the Pi/workstation:

```sh
python3 capture.py collect --port /dev/ttyACM0 --output boot-0.bcraw
```

Wait for `ARMED`, then power the BC250 normally. No board command or power
operation is performed by this script. A capture times out after 60 seconds;
Ctrl-C cancels. Decode on the workstation against the known working backup:

```sh
python3 tools/pico2-interposer/capture.py decode boot-0.bcraw \
  --rom output/pico2/private-20260926/CLEAN-working-backup.rom \
  --output boot-0.json
```

The buffer holds 786,432 four-bit samples: about **5.24 ms at 150 MHz**.
`--skip N` skips N complete CS# assertions before capturing the next one;
several normal boots with different skips may be needed to reach key/TOS
reads. The initial/final partial transactions are excluded. The raw decoder
handles both modes 0 and 3, short commands, full MISO data and optional ROM
comparison. An invalid CRC rejects the file; PIO/DMA stalls and low sampling
margin are reported. At 50 MHz SPI, 150 MHz sampling gives only three samples
per clock and is insufficient for a timing approval. This capture is a
measurement aid, not proof of a working active interposer.

## Check repeated captures on the workstation

Collect the same window during two separate normal boots, using the same
`--skip` value and different output filenames. Arm before powering the BC250
on each boot. Then compare the raw files against the working ROM:

```sh
python3 tools/pico2-interposer/qualify_capture.py boot-0a.bcraw boot-0b.bcraw \
  --rom output/pico2/private-20260926/CLEAN-working-backup.rom \
  --output boot-0-comparison.json
```

The script rechecks raw CRCs and ROM bytes, compares the common sequence of
complete reads, and reports minimum clock, CS setup/hold and CS-high intervals.
It subtracts one sample from each interval to account for sampling uncertainty.
For example, a sampled 100 ns half-cycle is too close to the model's 100 ns
limit to establish margin. It rejects discontinuities, conflicting captures,
unsupported read shapes/modes and intervals outside the modeled bounds.
`--commands N` explicitly limits the common prefix; any unexamined tail is
reported. Identical raw files cannot establish independent repeated boots.

A successful exit means only that the compared window passed this digital
screen. It does **not** identify copy/check passes, prove full boot coverage,
measure analogue output handover, or generate an armable board profile. The
first and last partial transactions are excluded, and an unobserved CS-high
gap before the first complete read is reported as missing. Captures from
different skip values must not be silently joined as one continuous trace.

## Interceptor: isolated bench first

Disconnect the BC250 and CH347 completely. The interceptor image also runs
the isolated Pi-to-Pico bench; no third UF2 is needed.

The prepared interceptor contains **638 synthetic transactions covering every one
of the signed pair's 318 changed words**. Its compressed command runs and replacement words use 2,468 bytes of SRAM.
A dedicated core expands the runs into the PIO FIFO ahead of each reply. It first searches for a PASS anchor with MISO forced off, ignoring
earlier unrelated or short requests. After that read completes, it checks the
next PASS guard read and remaining sequence strictly. It compares the complete
command/address before selecting a patch,
leaves ordinary reads with the original chip, and stops patching on a wrong
command or transaction length. A separate PIO state machine mirrors CS# after
the finite script ends. The PIO compares the header and starts a prepared reply without a CPU
interrupt; the CPU must keep its FIFO supplied, so feed latency still needs
physical measurement.

Use the same isolated Pi wiring, with GP6 left disconnected. Flash `bc250_interceptor.uf2`
with GPIO leads removed, reconnect the isolated bench, and run:

```sh
python3 router_bench.py --port /dev/ttyACM0 --isolated-pi-wiring \
  --profile router_profile.json
```

Start at 250 kHz. Later runs can use `--speed-hz 1000000` through `5000000`;
reset the isolated Pico between runs. `--wrong-address-after-anchor` is a negative
test that must latch an address fault. The runner also sends three unrelated or
short preamble transactions, which must be skipped without substitution.
With no original chip connected, this
bench checks substituted words and status; it cannot check original-chip MISO
or its electrical release. The digital model includes a separate original flash.

**This is not a captured BC250 boot profile.** The firmware has no board-arm
command. The modeled envelope is mode 0, exactly 64 clocks, at most 5 MHz,
at least 100 ns clock half-period/setup and 1 µs CS-high gaps. CPU response to
faults and analogue timing still need measurement; 25 MHz fails the local model.
See [validation and remaining measurements](../../docs/pico2-router-validation.md).

## Private payload preparation

`prepare_private.py` retains a new RSA-2048 signing key, re-signs the pinned
TOS and driver images, checks four native copy/check model cases and twenty
TOS component cases, then stores mode-0600 files inside a mode-0700 directory.
It refuses to overwrite an existing key/bundle. The first retained bundle is
`output/pico2/private-20260926/`, excluded from Git by `output/`.

Its `overlay.bin` is **198,240 bytes**: two type-50 variants, patched TOS and
re-signed driver entries. It preserves the original type-51 keys and includes
the tested TOS routine that appends the authentic VCN key in modeled RAM.
The key stays in `signer-private.pem`; only public material/signed components
belong in the Pico image. The full patched ROM is invalid by itself and must
never be programmed into the BC250 EEPROM.

The Pico router still needs a trace-derived profile identifying each module
read and the correct type-50 copy/check pass. No such profile is embedded and
no approved board UF2 is supplied. The address-checking router candidate is
implemented and locally tested; timing on real hardware remains to be measured.

## Build and local checks

Built with Pico SDK **2.3.1** (`079c6f39023649b154152db30f1d781e884879bc`), its
pinned TinyUSB submodule, and Raspberry Pi's **v2.3.1-0 RISC-V toolchain**.
The Pico 2 uses its supported Hazard3 core; PIO operation is independent of
whether the CPU runs Arm or RISC-V code. The passive and legacy router images
use 150 MHz; the two isolated RAM bench images explicitly set 200 MHz and
1.20 V for testing.

```sh
cmake -S tools/pico2-interposer -B output/pico2/build -G Ninja \
  -DPICO_SDK_PATH=/tmp/bc250-pico-sdk -DPICO_PLATFORM=rp2350-riscv \
  -DPICO_TOOLCHAIN_PATH=/tmp/bc250-pico-tools/riscv-toolchain-16-x86_64-lin \
  -Dpicotool_DIR=/tmp/bc250-pico-tools/picotool-2.3.1-x86_64-lin/picotool \
  -DBC250_ROUTER_PROFILE_HEADER="$PWD/output/pico2/router-v3-20260926/router_profile.h" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build output/pico2/build
PIOASM=output/pico2/build/pioasm/pioasm \
  BC250_OVERLAY_MANIFEST=output/pico2/private-20260926/MANIFEST.json \
  python3 -m unittest discover -s tools/pico2-interposer -p 'test_*.py' -v
```

The tests exercise byte order in both SPI modes, short-command resynchronizing,
CRC/length rejection, wrong-ROM detection, sampling warnings, and execute the
**assembled** reply PIO against a synthetic SPI master at 250 kHz–1 MHz with
an input synchronizer delay. They check output release on an aborted data
phase. These are local logic checks, not physical/analogue timing tests.
The router tests also execute its three assembled PIO programs against a
separate flash model, reject wrong addresses/opcodes, check every short length,
and replay the retained signed pair. `verify_router_build.py` checks that the
linked ELF has the same PIO instructions and exact command/reply words as the
model, and that the compressed tables and complete feed/fault loop are in SRAM.
All 44 local tests pass. The same C stream decoder also expands a 97,354-read
full-object stress profile exactly; its 2,636-byte compressed representation
replaces 1,168,248 bytes of literal triples. This is a synthetic capacity check,
not a measurement of the BC250 boot sequence.
The search/boundary decisions are compiled from the same `router_policy.h` as
the firmware and coupled to the PIO model. Injected monitor latencies exercise
short requests, insufficient gaps, bad anchor lengths, and a wrong guard read;
they do not establish the physical RP2350 monitor's execution time.

The earlier reply-only experiment remains in source for development and is
excluded from the normal build/kit (`BC250_BUILD_LEGACY_BENCH=ON` enables it).
The normal workflow uses only capture and interceptor images.

`patch_coverage.py` checks the four decoded physical traces against the two
retained ROMs and manifest, and writes a report without exposing the private
signer. It confirms address/byte coverage only; the active CS selector and
physical response timing are still untested. Leave the BIOS chip leg intact.

Official sources: [SDK release](https://github.com/raspberrypi/pico-sdk/releases/tag/2.3.1),
[toolchain release](https://github.com/raspberrypi/pico-sdk-tools/releases/tag/v2.3.1-0),
[Pico 2 datasheet](https://datasheets.raspberrypi.com/pico/pico-2-datasheet.pdf).
