/* RAM-only diagnostic layered on the proven powered VCN cache-map hook.
 * The original hook performs all 17 cache-window writes before this code
 * reads a host scratch marker. A marked call reports the selected VCN word
 * without the hook's usual reset=0 write. The unmarked path still performs
 * the original reset=0 write. Never flash this view to the BIOS EEPROM.
 */
.syntax unified
.thumb
.arch armv7-a
#ifndef BC250_DELAYED_SAMPLE_ADDR
#define BC250_DELAYED_SAMPLE_ADDR 0x20180 /* UVD_SOFT_RESET */
#endif

.section .map_branch, "ax", %progbits
.global bc250_delayed_reset_branch
.type bc250_delayed_reset_branch, %function
bc250_delayed_reset_branch:
    b.w bc250_delayed_reset_dispatch

.section .dispatch_cave, "ax", %progbits
.global bc250_delayed_reset_dispatch
.type bc250_delayed_reset_dispatch, %function
bc250_delayed_reset_dispatch:
    /* The original hook already pushed r4-r7, allocated eight scratch
     * bytes, wrote its control word, checked VCN power=0x800 and mapped
     * all 17 windows. Preserve the stack and callee-saved registers.
     */
    movs r0, #0
    str r0, [sp]
    ldr r0, =0x1f854             /* shared UVD_SCRATCH1 */
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 1f
    ldr r3, [sp]
    ldr r1, =0x5a13c0df
    cmp r3, r1
    bne 1f

    /* No UVD_SOFT_RESET write on the marked call. LOAD_IP_FW and the
     * cache-map stores already happened; this is their timing limitation.
     */
    movs r0, #0
    str r0, [sp]
    ldr r0, =BC250_DELAYED_SAMPLE_ADDR
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 2f
    ldr r0, [sp]
    bic.w r0, r0, #0xf0000000
    orr.w r0, r0, #0x70000000
2:  b.w bc250_postcache_map_failure

1:  /* Reproduce the reset address/value instructions we replaced. */
    ldr r0, =0x20180
    movs r1, #0
    b.w bc250_postcache_map_resume
    .balign 4, 0
