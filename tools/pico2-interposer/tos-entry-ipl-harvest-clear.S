/* RAM-only TOS-entry test of one volatile VCN harvest-register write.
 * Use the already measured IPL aperture. Write zero only if the early
 * 0x1f81c read is exactly 3; encode before/after via six original-flash
 * read addresses. No BIOS/Pico flash or eFuse-programming writes.
 */
.syntax unified
.cpu cortex-a5
.arm
.section .text, "ax", %progbits
.global tos_video_entry
tos_video_entry:
    mov r4, r0
    mov r5, lr
    ldr r8, =0x27c3fffc
    ldr r10, [r8]

    ldr r6, =0x0001f81c
    ldr r8, =0x0322003c
    mov r9, r6, lsr #4
    str r9, [r8]
    ldr r9, =0x02f1f81c
    ldr r7, [r9]

    /* Encode the value before any target write. */
    ldr r8, =0x27c40000
    uxth r10, r7
    add r10, r8, r10, lsl #2
    ldr r0, [r10]
    add r8, r8, #0x40000
    mov r10, r7, lsr #16
    add r10, r8, r10, lsl #2
    ldr r0, [r10]

    cmp r7, #3
    bne guard_failed
    mov r11, #0
    str r11, [r9]
    dsb sy
    isb
    ldr r11, [r9]
    b encode_after
guard_failed:
    mvn r11, #1          /* 0xfffffffe = guard failed; no target write */
encode_after:
    ldr r8, =0x27c40000
    uxth r10, r11
    add r10, r8, r10, lsl #2
    ldr r0, [r10]
    add r8, r8, #0x40000
    mov r10, r11, lsr #16
    add r10, r8, r10, lsl #2
    ldr r0, [r10]

    ldr r8, =0x27cffffc
    ldr r0, [r8]
    mov r0, r4
    mov lr, r5
    b original_entry
    .ltorg
