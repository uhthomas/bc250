/* RAM-only TOS-entry test: clear both already verified SEC_GASKET policy
 * words, then attempt a volatile harvest=0 write. Restore harvest if it
 * changed, restore both policy words, verify all restores, then run stock TOS.
 * Halt on an unexpected restore. No BIOS or Pico QSPI write.
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
    ldr r6, =0x0001f820
    bl read_word
    ldr r8, =0x00185103
    cmp r7, r8
    bne guard_failed
    ldr r6, =0x0001f8a4
    bl read_word
    cmp r7, #0xb
    bne guard_failed
    ldr r6, =0x0001f81c
    bl read_word
    cmp r7, #3
    bne guard_failed
    ldr r8, =0x27c3fff8
    ldr r10, [r8]

    ldr r6, =0x0001f820
    mov r7, #0
    bl write_word
    dsb sy
    bl read_word
    bl emit_value           /* policy 0x1f820 after clear */

    ldr r6, =0x0001f8a4
    mov r7, #0
    bl write_word
    dsb sy
    bl read_word
    bl emit_value           /* policy 0x1f8a4 after clear */

    ldr r6, =0x0001f81c
    mov r7, #0
    bl write_word
    dsb sy
    bl read_word
    mov r11, r7
    bl emit_value           /* harvest after write */
    cmp r11, #0
    bne harvest_unchanged
    mov r7, #3
    bl write_word
    dsb sy
    bl read_word
    bl emit_value           /* harvest after restore */
    cmp r7, #3
    bne restore_failed
    mov r11, #3
harvest_unchanged:
    ldr r6, =0x0001f8a4
    mov r7, #0xb
    bl write_word
    dsb sy
    bl read_word
    bl emit_value           /* 0x1f8a4 after restore */
    cmp r7, #0xb
    bne restore_failed

    ldr r6, =0x0001f820
    ldr r7, =0x00185103
    bl write_word
    dsb sy
    bl read_word
    bl emit_value           /* 0x1f820 after restore */
    ldr r8, =0x00185103
    cmp r7, r8
    bne restore_failed
    cmp r11, #3
    bne restore_failed
    ldr r8, =0x27c3fff0
    ldr r10, [r8]
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
