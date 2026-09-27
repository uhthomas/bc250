# Pico 2 six-wire MISO trial

Use the [physical pin diagram](pico2-six-wire-miso.svg). With both BC250 PSU
and Pico USB off, keep the existing five connections and add one direct wire:
J4004 MISO (bottom row, third contact when the white PCB triangle is below
VCC) to Pico GP5 (physical pin 7, left side with the USB socket at the top).
Leave J4004 VCC unconnected. The Pi connects to the Pico by USB only.

The BC250 flash's CS# pin 1 remains lifted and pulled up to its own pin 8
with 10 kΩ. Its yellow wire remains on Pico GP7 / physical pin 10. Do not
connect the lifted pin to J4004 CS# as well.

The `bc250_sparse_active` image is built for Pico 2 SRAM (`no_flash`); it
contains no SPI flash erase or program operation. After every Pico USB power
cycle, the persistent passive image starts instead. Load the candidate into
SRAM, check `status`, and issue exactly one of `arm-pass` or `arm-active`
while motherboard CS# is high. `arm-pass` keeps Pico MISO disabled. An active
arm uses the profile generated from the full verified boot trace and lets PIO
drive GP5 only after its 32-bit command guard matches a queued PATCH read.

On 2026-09-27, the first six-wire `arm-pass` PDU boot reached Fedora with
`systemctl is-system-running=running`. Pico status showed two completed profile
passes, 1,745,488 matched commands, zero mismatches, zero late decisions,
zero RX stalls and zero queued PATCHes. This confirms the additional MISO
wire did not disrupt the original-flash pass-through path while GP5 was
disabled. It does not yet validate active reply timing or PSP behavior.

One subsequent SRAM reload verified but the Pico did not enumerate on USB.
The Pi 5's RP1 `USB_VBUS_EN` GPIO42 (normal function `a2`, `VBUS_EN1`) was
briefly driven low and restored to `a2`; this power-reset the Pico remotely.
No active arm had occurred at that point. The Pi's persistent Pico flash image
remains passive and output-disabled.

## Exact-original active reply controls

The first active control returned the original four bytes `24 4b 44 42`
at `0x9dae08`. It queued and recognized one guarded PATCH command without a
PIO fault, but the BC250 stopped at 12,562 observed SPI commands and did not
reach Fedora.

A read-only [MISO probe](../tools/pico2-interposer/miso_probe.pio) captured
the original flash's `0x3b1e623e` at `0x9db140` during a successful
pass-through boot. A control image then supplied those same four bytes from
Pico GP5 at exactly that address. The probe captured `0x3b1e623e`, the PIO
recognized the guarded command and reported no late decision, FIFO stall or
profile mismatch, but the BC250 stopped at 842,666 observed SPI commands,
with 831,480 commands of the first profile pass matched. The same stop point
occurred with the [early-output selector](../tools/pico2-interposer/sparse_select_early.pio),
and again with early output plus 12 mA/fast-slew GP5 pad settings.

The last control also enabled the Pico input buffer on the isolated flash
CS# leg. It reported `flash_pad_high=1`, `flash_pad_low=0` when the guarded
command was recognized. That rules out the flash remaining digitally selected
through the response phase, but it does not measure its analogue rise time at
transaction start. The Pico's own MISO sampler cannot prove what the BC250
sampled at its input or establish setup and hold margin at the board pin.

The early selector was subsequently corrected to change each next MISO bit
after SCLK falls, matching the original flash's behavior. With that change,
exact-original active controls at an early key word and the last changed
payload word both booted Fedora. Re-signed clean TOS, a bypassed hook and a
no-op hook also booted; a hook dereferencing the offline fixture's
`0x10784010` address stopped boot, so that address cannot be assumed valid on
the physical board. The [direct type-51 trial](pico2-type51-vcn-trial.md)
then substituted the VCN2 usage-6 key during the copy read and passed live
PSP key recognition. Its unmodified VCN firmware load still failed with a
later status, and no hardware decode occurred. The board was restored to
Fedora with Pico MISO disabled and no BIOS or Pico flash writes.
