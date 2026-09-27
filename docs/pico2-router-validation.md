# Pico router: what is prepared and what is measured

2026-09-26. The retained signing key and signed payload are prepared. The
address-checking router is implemented and builds. The passive image has
booted on the Pico and reported outputs disabled. Its first capture triggered
but the USB transfer failed. Passive v0.2 is now flashed and its full
393,248-byte pattern/CRC self-test passes over the physical Pi/Pico USB link.
Two passive reboot traces now contain the same 2,133 complete reads, all
matching the working ROM, at about **33.27 MHz SPI**. The Pico remains at
150 MHz. The current interceptor fails the measured timing and its offline
480 MHz replay; see the [measurement report](pico2-measured-timing.md).
**No physical interceptor test is available.** Keep the five-wire passive
connection in the [wiring guide](pico2-wiring.md) while revising the active path.

## Actual artifacts

- `output/pico2/private-20260926/signer-private.pem`: retained RSA-2048 signer,
  mode 0600 in a 0700 directory, excluded from Git. It is not staged on the Pi
  or embedded in any Pico image.
- The same directory contains the independently verified signed TOS/driver,
  a 198,240-byte overlay, and the original/patched comparison ROMs. The patched
  full ROM must never be programmed into the BC250 EEPROM.
- `output/pico2/router-v3-20260926/router_profile.json`: **synthetic**
  isolated test sequence, 638 rows covering all 318 changed 32-bit words,
  with two initial PASS guard reads.
  It returns the original key words on the second key pass, and patched TOS
  and driver words on both of their passes. This is coverage, not evidence
  of the actual board's read order.
- `output/pico2/ready/`: **two images**, `bc250_passive.uf2` and `bc250_interceptor.uf2`,
  matching scripts, public/signed payloads and diagrams. The same kit is staged
  on the Pi at `/home/pi/bc250-pico2-20260926`.

## Router operation

An independent PIO state machine forwards motherboard CS# to the isolated
flash CS#. The response state machine has the next expected command and reply
ready before the transaction. It receives all 32 command/address bits and
compares them before taking the patch path. That path raises flash CS#, allows
time for the chip to release MISO, then sends the prepared word. On a pass row,
the original flash stays selected and the Pico never drives MISO.

Before the recorded window, MISO is forced off at the GPIO output override.
Unrelated complete commands and short commands are passed through while the
receiver repeatedly searches for the first PASS anchor. Its expected address,
PASS directive and reply FIFO are preserved across receive resets. A complete
64-clock anchor locks the sequence; the following PASS guard must also match
before a patch can be emitted. A malformed read of the exact anchor is terminal.
The example anchors are synthetic; real anchors still need the board trace.

A wrong command/address latches a PIO fault before any replacement data is
emitted. A second, input-only PIO block counts the clocks in each selected
transaction. A dedicated CPU core checks for 64 clocks and a legal transaction
boundary. Fault handling disables Pico MISO and stops the response engine;
the CS mirror continues forwarding subsequent transactions. After the finite
script finishes, only the CS mirror remains active.

All outputs start disabled and require `arm-isolated`. The supplied firmware
has no board-arm command. The private signing key is never needed on the Pico.

## Local evidence

The 44-test local suite includes execution of the **assembled PIO instructions**
against a separate digital flash model. It checks:

- Substitution, ordinary reads, repeated-address copy/check selection, and
  original-flash pass-through after the script ends.
- Wrong addresses, unaligned addresses and wrong opcodes stopping the script.
- Every short transaction length from 1 through 63 clocks, and an 80-clock
  transfer being detected by the independent clock counter.
- No overlap between Pico and modeled flash MISO drive in the supported tests.
- Every changed word of the actual retained signed pair, in SPI byte order.
- Search through short/unrelated preamble traffic with zero Pico MISO drive,
  exact-anchor length checks, strict rejection after the anchor, and return to
  original-flash reads after a truncated patch transaction.

Tested digital conditions: 150 MHz PIO, mode 0, four-byte READ03, 250 kHz–5 MHz,
2–3 cycles of input synchronization, 12/64/128-cycle FIFO word service, 100 ns or
longer clock half-periods and CS-to-first-clock setup, and 1 µs CS-high gaps.
The flash model allows two PIO cycles (13.3 ns) before releasing its output.
A 25 MHz negative test fails; no higher-speed compatibility is claimed.

`build-validation.json` verifies the linked ELF's three PIO programs and every
command/branch/reply word against the tested model by expanding the actual
linked runs with the same C decoder used by the firmware. Its 2,468-byte
compressed profile and complete 764-byte feed/fault-monitor loop reside in
SRAM; the monitor makes no calls back into Pico program flash. Both UF2 generation and compiler warnings pass.
The native firmware/signature work separately passed four copy/check controls
and twenty TOS-entry model cases.

The boundary/search policy is host-compiled from the same C header used by the
firmware, then coupled to the PIO model with injected response latencies of
8, 32 and 80 cycles. These checks do **not** model analogue signal quality or
execute the RP2350 monitor cycle by cycle. The 1 µs gap is a bench qualification
target, not a measured fault-response guarantee. The isolated Pi bench cannot test a real
flash chip's output release because no flash is connected there.

`qualify_capture.py` separately checks repeated raw windows against the working
ROM. It rejects ordering/data changes, capture discontinuity, unsupported clock
polarity/read lengths and CS/clock intervals outside the current model. Timing
bounds include one sample of quantization margin; unknown initial CS-high time
and unexamined tails are explicit. It never labels its report a complete boot
or a ready board profile. These checks are covered by positive and negative
synthetic captures. The two real windows match each other and the ROM but
fail the current timing limits. `replay_capture.py` separately tests the
assembled response logic against recorded edges at modeled system clocks.

## Measurements still needed

1. Extend the measured early bootloader windows to cover target key/TOS/driver
   reads and cold-boot ordering. Resolve analogue setup and handover timing;
   the initial digital measurements alone cannot qualify active outputs.
2. Run the isolated bench using the interceptor image, starting at 250 kHz. Confirm
   positive replies, negative address handling, and short-transfer fault timing.
3. Compare recorded target bytes with the working backup and identify the
   actual type-50 copy/check passes and all TOS/driver reads. Build the strict
   board profile from that evidence. The current sparse synthetic sequence
   cannot simply be relabeled as a board profile.
4. Only if the measured timing fits, qualify the CS isolation and shared-MISO
   timing on the actual board before attempting a boot with substitutions.
   If the bus is faster, the current router needs a different timing design;
   an untested overclock is not assumed to solve it.

The board profile also has to fit the implementation's 384 KiB SRAM budget.
Sequential PASS/PATCH runs now use 12 bytes per run, plus four bytes per
substituted word. The full-object stress case covers 97,354 reads (both copies
of type50, TOS and driver), expands to 1,168,248 bytes of literal triples, and
fits in **2,636 bytes** of compressed SRAM data. Its expansion is checked using
the firmware's actual C stream decoder. Real ordering may compress differently;
the trace-derived profile must still be checked independently. Core1 feeds
expanded words into PIO ahead of use; its physical throughput is unmeasured.

Active power sequencing needs qualification too: the target must be powered
before a Pico output can drive one of its flash pins. The passive five-wire
stage has all outputs disabled; its USB-first sequence is not an active-arm recipe.

No BC250 EEPROM writes, reboots or GPIO transactions were performed while
preparing these artifacts.
