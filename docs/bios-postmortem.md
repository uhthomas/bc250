# BIOS boot failure: evidence and remaining questions

Updated 2026-09-25. The board failed to return after the video-key BIOS trial.
The exact failing instruction or hardware check is **not known**. The failed
image must not be flashed again unchanged.

## What changed

The control image, containing the internal PSP bootloader and the original
signing keys, booted successfully after both a reboot and a physical PSU cycle.
The next image replaced that bootloader's embedded root public key, re-signed
the boot and runtime key databases and debug public-key object, and added the
published VCN video-firmware verification key. The enlarged runtime database
also moved to a different flash offset, with its directory entry updated.

The modified image was written and read back in full. That independent readback
matches the prepared image exactly. Compared with the working control backup,
3,787 bytes changed, all inside the intended component regions. Bootloader
instructions outside its embedded key object are unchanged. The board then
failed to return over SSH and the user reported no display after power cycling.

Restoring the working control on 2026-09-25 recovered normal boot. This strongly
implicates the firmware changes, but does not locate the failing check. No decoder test was
reached. A successful flash verification proves the stored bytes match the
file; it does not prove the processor can boot that file.

## What went wrong with the validation

The pre-flash tests exercised real firmware instructions for parsing, key
selection and signatures, with software implementations of hashing, RSA and
memory copying. They supplied security flags, directory contents, version
policy and earlier initialization state. They did not execute the boot ROM,
the complete boot sequence, real crypto hardware or the final firmware handoff.

Those limits were recorded, but they remained unresolved at the time of the
experiment. Booting the control established that the complete image could
boot; it did not prove execution of the internal bootloader we replaced.
The duplicate-copy finding below invalidates my earlier, stronger claim that
the control demonstrated that bootloader working with the original trust chain.
It also did not establish that substituting its root key would work. I should
have had a tested external recovery path
before proceeding with that experiment. User approval did not resolve the
technical uncertainty.

## Duplicate bootloader copy found after recovery

An offline comparison on 2026-09-25 found the same complete 43,008-byte encrypted
bootloader at flash offset `0x821000` in seven saved full images: original
MeiMei, vendor public/internal P3, restored control, failed trial readback, and
the two later root-preserving trial readbacks. Our bootloader changes were at
the directory-listed `0x8e0400`; the copy at `0x821000` was unchanged throughout.
Even the vendor internal image retains that encrypted copy.

This supplies a plausible explanation for both outcomes. If the unchanged
copy executes, it would still use the original root key and could reject the
re-signed objects in the failed image. It would also never execute the later
video-key addition. **This is a hypothesis, not a captured cause of the failure.**

A saved community SPI trace starts with reads from `0x821000`, but reports
383,613 PIO overflows. It is from another board and cannot establish an absence
of reads from other regions. A separate
[primary BC250 investigation](https://habr.com/ru/companies/pt/articles/979470/)
also reports initial reads from this address, with bytes matching our encrypted
copy. Neither establishes which instructions ran on the user's board.

The reproducible local comparison is
`output/video-decode-20260922/psp-analysis/audit-bootloader-copies.py`, with
results in `bootloader-copies.json` and discussion in `BOOTLOADER_COPIES.md`
under the investigation directory. No firmware was generated or flashed for
this analysis. Replacing the second copy with plaintext is **not** yet validated:
boot-ROM acceptance remains unknown. The user authorizes future flashing
without another permission request only when we have a high-confidence fix,
with as much testing as possible performed locally first.

The follow-up local audit acquired a publicly shared ROM dump and executed
58 bounded native cases. With the historical status value `0x80f1a`, that ROM
selects a separate secure-container loader, while the directory path can load
our patched copy under a different mode. Four early crypto-error controls go
to the fatal handler without entering the directory loader. This strengthens
the unused-copy explanation and argues against blindly patching `0x821000`.
However, this ROM was not read from our board, and the historical host-register
alias/early-boot state remain unproven. Evidence and limits are in
`output/video-decode-20260922/BOOTROM_SELECTION.md`; no new firmware was written.

## Additional offline investigation

The postmortem rechecked the exact saved control and failed readback, then
extended the previous debug-signature test through its native caller at
`0x2f3c`. Twelve cases cover both images, zero/A5 initial memory fills, intact
signatures, corrupted signatures and a policy branch that skips debug setup.

Both intact images pass this caller under the explicit hardware fixtures.
Corrupted signatures clear the debug object, leave debug disabled, record
status `0x993`, and return zero. That particular rejection path is therefore
not itself an immediate fatal halt. This weakens a simple debug-signature
formatting explanation; it does not exclude later debug-handshake behavior.

A separate native trace confirms that the fatal logger writes a status word
to PSP address `0x032000d8` and spins at `0x7cf6`. These are emulator observations,
not a captured error from the failed board. Reading the SPI flash alone cannot
recover that live register value.

The remaining untested boundaries include boot-ROM policy for the changed
root key, physical crypto/key provisioning, directory initialization, relocation
and subsequent firmware modules. None is established as the cause. Lack of
UEFI Secure Boot does not by itself demonstrate that PSP firmware accepts a
replacement trust chain.

Evidence is retained under `output/video-decode-20260922/psp-analysis/`:

- `audit-failed-boot.py`: offline reproducer; reads saved images only.
- `failed-boot-audit.json`: twelve passing cases, fixtures and scope limits.
- `failed-boot-selected-disassembly.txt`: relevant unchanged bootloader code.

No new ROM was generated, and no hardware was accessed during this audit.

After recovery, a further bounded test compared boot key-derivation requests
from the exact two bootloaders. All seven key purposes made identical requests
without reading either root-key copy. This checks a direct software dependency
only: AES results were synthetic, HMAC ran in software, and earlier hardware
key provisioning remains unknown. See
`output/video-decode-20260922/ROOT_KDF_DEPENDENCY.md` for the controls and limits.
It provides no basis for another BIOS write.

A subsequent native directory-initialization test also finds both databases
in the exact failed image, including the relocated runtime database, through
the bootloader's initial upper-8-MiB flash window. Hardware mapping and crypto
remain fixtures; no layout fault was found. The bootloader's optional POST
logger and the board's accessible Nuvoton POST UART registers provide a possible
diagnostic route, but the output mux is not selected and no physical capture
has been verified. Evidence and limits are in
`output/video-decode-20260922/DIRECTORY_BOOTSTRAP.md` and `BOOT_OBSERVABILITY.md`.

Read-only PCI inspection subsequently confirmed that port-80 LPC forwarding
is enabled in the recovered running system. A documented FCH last-byte read
could not proceed: Fedora denied the prerequisite `/dev/mem` base-register
read. No diagnostic code was obtained, no hardware setting changed, and no
OS protection was disabled. Boot-time physical capture is still unverified.

## What the recovery equipment can establish

On 2026-09-25 the Waveshare CH347T successfully identified the flash through
J4004 and completed a full 16 MiB read at 468.75 kHz. The external backup was
copied to the workstation and matches **both the exact image written and the
original post-write readback, byte for byte**. The user requested cancelling
the second external read in favour of this comparison; it was stopped and is
not used as evidence.

There are zero changed bytes relative to the failed image, including its
settings areas. This confirms that the chip still holds the intended failed
image; persistent storage corruption does not explain the difference between
what we intended to write and what is present now. It does not identify the
failing boot check. Restoration and a successful boot were subsequently verified
as described below.

Evidence: `output/waveshare-recovery-20260925/connection-ZTskeUrB/`, including
the external backup, probe/read logs and `workstation-verification.json`.
The [Waveshare recovery guide](waveshare-j4004.md) records this connection.

The working control image was restored through the Waveshare on 2026-09-25.
Full write verification passed, followed by a separate full readback that
matches the control image exactly. The recovery service completed at 14:57:52
UTC. The user then powered the BC250 on, and SSH confirmed a fresh boot at
15:01:41 UTC, boot ID `a5928f41-9efe-4640-b677-3ce4811b1c5b`. The normal bootc
image is running with 8 cores/16 threads, working CPU frequency scaling and idle
states, and no failed services. The CU restore service completed. The existing
amdgpu display-interrupt warnings and SDMA fallback remain; the normal driver
does not register VCN. Full health evidence is retained in
`output/waveshare-recovery-20260925/post-recovery-health.log`.

Successful recovery provides stronger evidence that the firmware contents caused
the outage. It does not identify which trust-chain or placement change caused it,
and does not establish working hardware video decoding.

Working control SHA256:
`f1251268fc129d6799fcb75041017ee739250d71b7c9d1981d67016923834183`

Failed image/readback SHA256:
`1b43de5733bfeebd79639f855eaff4eba2f19141969a45eb2fc7e91e987b3d2f`
