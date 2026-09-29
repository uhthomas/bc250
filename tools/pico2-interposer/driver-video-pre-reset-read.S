/* RAM-only diagnostic. Read a VCN register before the signed driver writes
 * its separate control word at 0x1f8a4. Normally select the powered request
 * after host VCPU release; BC250_EARLY_UVD_HARVEST selects the first request
 * before host VCN initialization. Never flash this ROM view.
 */
.syntax unified
.thumb
.arch armv7-a
#ifndef BC250_READBACK_TARGET
#define BC250_READBACK_TARGET 0x20180 /* UVD_SOFT_RESET, VCN 2.0 segment 1 */
#endif
#if (defined(BC250_CLEAR_UVD_HARVEST) || defined(BC250_EARLY_UVD_HARVEST) || defined(BC250_DIRECT_EARLY_UVD_HARVEST)) && BC250_READBACK_TARGET != 0x1f81c
#error Harvest clear must target CC_UVD_HARVESTING at 0x1f81c
#endif

.section .pre_reset_hook, "ax", %progbits
.global bc250_pre_reset_hook
.type bc250_pre_reset_hook, %function
bc250_pre_reset_hook:
    b.w bc250_pre_reset_read

.section .map_cave, "ax", %progbits
.global bc250_pre_reset_read
.type bc250_pre_reset_read, %function
bc250_pre_reset_read:
    sub sp, #8
#ifndef BC250_DIRECT_EARLY_UVD_HARVEST
    movs r0, #0
    str r0, [sp]
    ldr r0, =0x1f810
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 2f
    ldr r0, [sp]
#ifdef BC250_EARLY_UVD_HARVEST
    ldr r1, =0x801
    cmp r0, r1
#else
    cmp.w r0, #0x800
#endif
    bne 1f
#endif

    /* Return the low 28 bits before the original signed-driver control
     * write at 0x1f8a4. The early variant aborts the first VCN load.
     */
    movs r0, #0
    str r0, [sp]
    ldr r0, =BC250_READBACK_TARGET
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 2f
#ifdef BC250_CLEAR_UVD_HARVEST
    /* Only the measured 0x3 state permits this reversible one-word trial.
     * Read back before reporting; the diagnostic response aborts GPU probe.
     */
    ldr r1, [sp]
    cmp r1, #3
    bne 3f
    movs r1, #0
    ldr r0, =BC250_READBACK_TARGET
    movs r2, #4
    svc #0x7c
    cbnz r0, 2f
    movs r0, #0
    str r0, [sp]
    ldr r0, =BC250_READBACK_TARGET
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 2f
3:
#elif defined(BC250_ENABLE_VCPU_TRACE)
    /* The PSP route may reach TRCE_EN even when the host RMW did not. */
    ldr r1, [sp]
    orr.w r1, r1, #0x400
    ldr r0, =BC250_READBACK_TARGET
    movs r2, #4
    svc #0x7c
    cbnz r0, 2f
    movs r0, #0
    str r0, [sp]
    ldr r0, =BC250_READBACK_TARGET
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 2f
#endif
    ldr r0, [sp]
    bic.w r0, r0, #0xf0000000
    orr.w r0, r0, #0x70000000
    add sp, #8
    b.w bc250_postload_readback_failure

1:  /* Preserve the original pre-power reset write and continuation. */
    add sp, #8
    ldr r0, =0x1f8a4
    movs r1, #1
    movs r2, #4
    svc #0x7c
    b.w bc250_original_reset_resume

2:  /* Propagate a PSP read error without pretending a reset value. */
    add sp, #8
    b.w bc250_postload_readback_failure
    .balign 4, 0
