/* Report a PSP-side SMN read after both signed-driver reset writes.
 * A successful read is encoded as 0x7nnnnnnn, carrying the low 28 bits of
 * the observed word. This deliberately fails this ONE diagnostic VCN load.
 * SVC errors propagate unchanged. Never write this ROM to the BIOS EEPROM.
 */
.syntax unified
.thumb
.arch armv7-a

#ifndef BC250_READBACK_TARGET
#define BC250_READBACK_TARGET 0x0900c004
#endif

.section .readback_hook, "ax", %progbits
.global bc250_reset_readback_hook
.type bc250_reset_readback_hook, %function
bc250_reset_readback_hook:
    b.w bc250_reset_readback

.section .readback_cave, "ax", %progbits
.global bc250_reset_readback
.type bc250_reset_readback, %function
bc250_reset_readback:
    ldr r1, [sp, #0x14]
    movw r2, #0xffff
    cmp r1, r2
    bne 1f
    cbnz r0, 3f
1:
    ldr r0, =0x1f8a4
    movs r1, #1
    movs r2, #4
    svc #0x7c
    cbnz r0, 3f
    /* Other contexts follow the unmodified success path. */
    ldr r1, [sp, #0x14]
    movw r2, #0xffff
    cmp r1, r2
    bne 4f

    /* The stock driver itself calls SVC 7b with (SMN, out*, width).
     * Keep the output inside an aligned temporary stack slot.
     */
    sub sp, #8
    movs r0, #0
    str r0, [sp]
    ldr r0, =BC250_READBACK_TARGET
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 2f
    ldr r0, [sp]
    bic.w r0, r0, #0xf0000000
    orr.w r0, r0, #0x70000000
2:
    add sp, #8
3:
    b.w bc250_postload_readback_failure
4:
    b.w bc250_postload_readback_success
    .balign 4, 0
