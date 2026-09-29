/* Probe one early, volatile fabric bit before TOS. Require the measured
 * BC250 baseline (fabric=f0, core-mask=77, harvest=3), write 8f0, read the
 * fabric and harvest words, restore f0, and verify the fabric restore.
 * Both outcomes are encoded in original-flash read addresses. Stop rather
 * than boot if the fabric word cannot be restored. No flash write.
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
    ldr r10, [r8]           /* start */

    ldr r6, =0x00050d6c
    bl read_word
    cmp r7, #0xf0
    bne guard_failed
    ldr r6, =0x0005a870
    bl read_word
    cmp r7, #0x77
    bne guard_failed
    ldr r6, =0x0001f81c
    bl read_word
    cmp r7, #3
    bne guard_failed
    ldr r8, =0x27c3fff8
    ldr r10, [r8]           /* guard passed */

    ldr r6, =0x00050d6c
    ldr r7, =0x000008f0
    bl write_word
    dsb sy
    bl read_word
    bl emit_value           /* fabric after bit-11 set */

    ldr r6, =0x0001f81c
    bl read_word
    bl emit_value           /* harvest with bit 11 set */

    ldr r6, =0x00050d6c
    mov r7, #0xf0
    bl write_word
    dsb sy
    bl read_word
    bl emit_value           /* fabric after restore */
    cmp r7, #0xf0
    bne restore_failed

    ldr r6, =0x0001f81c
    bl read_word
    bl emit_value           /* harvest after restore */
    ldr r8, =0x27c3fff0
    ldr r10, [r8]           /* safe end */
    b continue_stock

guard_failed:
    ldr r8, =0x27c3ffe0
    ldr r10, [r8]
    b continue_stock
restore_failed:
    ldr r8, =0x27c3ffec
    ldr r10, [r8]
1:  b 1b

continue_stock:
    mov r0, r4
    mov lr, r5
    b original_entry

read_word:
    ldr r8, =0x0322003c
    mov r9, r6, lsr #4
    str r9, [r8]
    ldr r9, =0x000fffff
    and r9, r6, r9
    ldr r8, =0x02f00000
    add r9, r8, r9
    ldr r7, [r9]
    bx lr

write_word:
    ldr r8, =0x0322003c
    mov r9, r6, lsr #4
    str r9, [r8]
    ldr r9, =0x000fffff
    and r9, r6, r9
    ldr r8, =0x02f00000
    add r9, r8, r9
    str r7, [r9]
    bx lr

emit_value:
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
