/* RAM-only experiment: apply the pinned Cezanne/Renoir client-12 gasket
 * transaction before Trusted OS, then emit the descriptor's low 16 bits as
 * one original-flash read address. The reference policy is not a production
 * BC250 policy. This component must only be served by the active interposer;
 * the generated ROM view must never be flashed to the BIOS EEPROM.
 */
.syntax unified
.cpu cortex-a5
.arm
.section .text, "ax", %progbits
.global tos_video_entry
tos_video_entry:
    adr r4, bc250_gasket12_table
    mov r5, #51
    ldr r6, =0x0322003c
    ldr r7, =0x02f00000
1:
    ldmia r4!, {r8, r9}
    mov r10, r8, lsr #4
    str r10, [r6]
    ubfx r10, r8, #0, #20
    str r9, [r7, r10]
    subs r5, r5, #1
    bne 1b
    dsb sy

#ifndef BC250_NO_DIAG
    ldr r8, =0x0900c9a0
    mov r10, r8, lsr #4
    str r10, [r6]
    ubfx r10, r8, #0, #20
    ldr r11, [r7, r10]
    ldr r12, =0x27c40000
    uxth r10, r11
    add r12, r12, r10, lsl #2
    ldr r10, [r12]
#endif

    b original_entry
    .ltorg

#include "gasket12-reference.inc"
