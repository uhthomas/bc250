/* RAM-only first-instruction TOS diagnostic using the IPL's direct SMN
 * aperture algorithm. No BIOS or Pico flash writes. A fixed SPI marker is
 * read before the possibly blocking aperture access; two addresses then
 * encode the 32-bit result and a final fixed marker proves continuation.
 * The first physical trial should use the IPL's known 0x5a870 core-mask
 * read as a control. Only after that succeeds should 0x1f81c be considered.
 */
#ifndef BC250_PROBE_ADDR
#error BC250_PROBE_ADDR is required
#endif
#if BC250_PROBE_ADDR != 0x5a870 && BC250_PROBE_ADDR != 0x1f81c
#error Only the pinned core-mask control and VCN harvest candidate are allowed
#endif
.syntax unified
.cpu cortex-a5
.arm
.section .text, "ax", %progbits
.global tos_video_entry
tos_video_entry:
    mov r4, r0
    mov r5, lr

    /* Original flash, final MiB: capture this before touching the aperture. */
    ldr r8, =0x27c3fffc
    ldr r10, [r8]

    /* Exact shape of IPL FUN_00007db8: selector <- address >> 4,
     * read 0x02f00000 | (address & 0xfffff). The TOS initializes its own
     * selector later, so we do not guess an earlier selector to restore. */
    ldr r6, =BC250_PROBE_ADDR
    ldr r8, =0x0322003c
    mov r9, r6, lsr #4
    str r9, [r8]
    ldr r9, =0x000fffff
    and r9, r6, r9
    ldr r8, =0x02f00000
    add r9, r8, r9
    ldr r7, [r9]

    /* Two 16-bit words in separate 256-KiB lanes. */
    ldr r8, =0x27c40000
    uxth r9, r7
    add r9, r8, r9, lsl #2
    ldr r10, [r9]
    add r8, r8, #0x40000
    mov r9, r7, lsr #16
    add r9, r8, r9, lsl #2
    ldr r10, [r9]

    ldr r8, =0x27cffffc
    ldr r10, [r8]
    mov r0, r4
    mov lr, r5
    b original_entry
    .ltorg
