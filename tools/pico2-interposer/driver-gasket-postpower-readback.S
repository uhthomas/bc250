/* RAM-only PSP diagnostic: allow the first VCN firmware load to finish.
 * The kernel's second LOAD_IP_FW occurs after VCN PGFSM power-up. Distinguish
 * it by the already-verified UVD_POWER_STATUS change 0x801 -> 0x800, then
 * report one PSP-side SMN read as status 0x7nnnnnnn. By default this is
 * the cold-reset word; BC250_READBACK_CACHE selects VCN cache BAR low.
 * Both signed-driver reset writes execute before either branch. Never flash.
 */
.syntax unified
.thumb
.arch armv7-a

.section .readback_hook, "ax", %progbits
.global bc250_reset_readback_hook
.type bc250_reset_readback_hook, %function
bc250_reset_readback_hook:
    b.w bc250_postpower_readback

.section .gasket_readback_cave, "ax", %progbits
.global bc250_postpower_readback
.type bc250_postpower_readback, %function
bc250_postpower_readback:
    /* Preserve the original first reset-service failure for context ffff. */
    ldr r1, [sp, #0x14]
    movw r2, #0xffff
    cmp r1, r2
    bne 1f
    cbnz r0, 5f
1:
    ldr r0, =0x1f8a4
    movs r1, #1
    movs r2, #4
    svc #0x7c
    cbnz r0, 5f
    ldr r1, [sp, #0x14]
    movw r2, #0xffff
    cmp r1, r2
    bne 6f

    sub sp, #8
    movs r0, #0
    str r0, [sp]
    ldr r0, =0x1f810
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 4f
    ldr r0, [sp]
    cmp.w r0, #0x800
    bne 4f

    /* Only the post-power call reports the selected register. */
    movs r0, #0
    str r0, [sp]
#ifdef BC250_READBACK_CACHE
    ldr r0, =0x2107c
#else
    ldr r0, =0x0900c004
#endif
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 3f
    ldr r0, [sp]
    bic.w r0, r0, #0xf0000000
    orr.w r0, r0, #0x70000000
3:
    add sp, #8
5:
    b.w bc250_postload_readback_failure
4:
    add sp, #8
6:
    movs r0, #0
    b.w bc250_postload_readback_success
    .balign 4, 0
