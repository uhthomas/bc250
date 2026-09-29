/* First-instruction TOS diagnostic. Encode svc #0x7b's return status and
 * 0x1f81c sample in four original-flash read addresses. No flash writes.
 * The Pico records addresses after its verified boot profile completes.
 */
.syntax unified
.cpu cortex-a5
.arm
.section .text, "ax", %progbits
.global tos_video_entry
tos_video_entry:
    mov r4, r0
    mov r5, lr
    adr r1, sample
    mov r3, #0
    str r3, [r1]
    ldr r0, =0x1f81c
    mov r2, #4
    svc #0x7b
    mov r6, r0
    ldr r7, sample

    /* Each 16-bit halfword selects a word-aligned address in a 256-KiB
     * lane of the last MiB. The loaded value is deliberately discarded. */
    ldr r8, =0x27c00000
    uxth r9, r6
    add r9, r8, r9, lsl #2
    ldr r10, [r9]
    add r8, r8, #0x40000
    mov r9, r6, lsr #16
    add r9, r8, r9, lsl #2
    ldr r10, [r9]
    add r8, r8, #0x40000
    uxth r9, r7
    add r9, r8, r9, lsl #2
    ldr r10, [r9]
    add r8, r8, #0x40000
    mov r9, r7, lsr #16
    add r9, r8, r9, lsl #2
    ldr r10, [r9]

    mov r0, r4
    mov lr, r5
    b original_entry
    .balign 4, 0
sample:
    .word 0
    .ltorg
