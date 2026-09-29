/* Read a bounded slice of decrypted IPL before TOS overwrites address zero. Encode
 * each 16-bit halfword in a read address of the original BIOS flash.
 * DUMP_OFFSET is the byte offset and DUMP_HALFWORDS is at most 32768.
 */
.syntax unified
.cpu cortex-a5
.arm
.section .text, "ax", %progbits
.global tos_video_entry
tos_video_entry:
    mov r10, r0
    mov r11, lr
    ldr r4, =DUMP_OFFSET
    movw r5, #DUMP_HALFWORDS
    ldr r8, =0x27c00000
#ifdef DUMP_MARKED
    /* Delimit the requested slice from unrelated BIOS reads in this window. */
    ldr r7, =0x27c3fffc
    ldr r9, [r7]
    sub r7, r7, #4
    ldr r9, [r7]
    sub r7, r7, #4
    ldr r9, [r7]
#endif
next_halfword:
    ldrh r6, [r4], #2
    add r7, r8, r6, lsl #2
    ldr r9, [r7]
    subs r5, r5, #1
    bne next_halfword
#ifdef DUMP_MARKED
    ldr r7, =0x27c3fff0
    ldr r9, [r7]
    sub r7, r7, #4
    ldr r9, [r7]
    sub r7, r7, #4
    ldr r9, [r7]
#endif
    mov r0, r10
    mov lr, r11
    b original_entry
    .ltorg
