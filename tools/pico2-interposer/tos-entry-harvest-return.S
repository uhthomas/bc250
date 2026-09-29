/* First-instruction TOS control: issue the same PSP read request as the
 * harvest guards, then resume stock reset regardless of its result.
 * RAM-only interposer use; no host VCN access or flash writes.
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
    mov r0, r4
    mov lr, r5
    b original_entry
    .balign 4, 0
sample:
    .word 0
    .ltorg
