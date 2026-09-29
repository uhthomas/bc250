/* Read three selected SMN words before the TOS body runs. Each value is
 * encoded in original-BIOS SPI read addresses; this hook performs no writes
 * except to the IPL's transient SMN aperture selector.
 */
#ifndef READ_FIRST
#define READ_FIRST 0x0001f820
#endif
#ifndef READ_SECOND
#define READ_SECOND 0x0001f8a4
#endif
#ifndef READ_THIRD
#define READ_THIRD 0x0001f81c
#endif
.syntax unified
.cpu cortex-a5
.arm
.section .text, "ax", %progbits
.global tos_video_entry
tos_video_entry:
    mov r4, r0
    mov r5, lr

    ldr r8, =0x27c3fffc
    ldr r10, [r8]           /* begin */
    ldr r6, =READ_FIRST
    bl read_and_emit
    ldr r8, =0x27c3fff8
    ldr r10, [r8]
    ldr r6, =READ_SECOND
    bl read_and_emit
    ldr r8, =0x27c3fff4
    ldr r10, [r8]
    ldr r6, =READ_THIRD
    bl read_and_emit
    ldr r8, =0x27c3fff0
    ldr r10, [r8]           /* end */

    mov r0, r4
    mov lr, r5
    b original_entry

read_and_emit:
    ldr r8, =0x0322003c
    mov r9, r6, lsr #4
    str r9, [r8]
    ldr r9, =0x000fffff
    and r9, r6, r9
    ldr r8, =0x02f00000
    add r9, r8, r9
    ldr r7, [r9]

    ldr r8, =0x27c40000
    uxth r9, r7
    add r9, r8, r9, lsl #2
    ldr r10, [r9]
    add r8, r8, #0x40000
    mov r9, r7, lsr #16
    add r9, r8, r9, lsl #2
    ldr r10, [r9]
    bx lr
    .ltorg
