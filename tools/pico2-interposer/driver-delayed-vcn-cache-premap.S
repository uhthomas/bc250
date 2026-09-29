/* RAM-only PSP diagnostic. Read a VCN cache word after the first Linux VCPU
 * wait and BEFORE the signed driver's 17 cache-window replay writes.
 * The unmarked path exactly resumes the proven map/reset sequence.
 * Never flash this interposer view to the BC250 BIOS EEPROM.
 */
.syntax unified
.thumb
.arch armv7-a

#ifndef BC250_PREMAP_SAMPLE_ADDR
#define BC250_PREMAP_SAMPLE_ADDR 0x2010c
#endif

.section .premap_branch, "ax", %progbits
.global bc250_premap_branch
bc250_premap_branch:
    b.w bc250_premap_dispatch

.section .dispatch_cave, "ax", %progbits
.global bc250_premap_dispatch
bc250_premap_dispatch:
    /* The original hook pushed r4-r7, allocated eight scratch bytes and
     * checked UVD_POWER_STATUS=0x800. No cache-window store has run yet.
     */
    movs r0, #0
    str r0, [sp]
    ldr r0, =0x1f854         /* shared UVD_SCRATCH1 marker */
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 1f
    ldr r3, [sp]
    ldr r1, =0x5a13c0df
    cmp r3, r1
    bne 1f

    /* Marked request: capture the existing word before any replay. */
    movs r0, #0
    str r0, [sp]
    ldr r0, =BC250_PREMAP_SAMPLE_ADDR
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, 2f
    ldr r0, [sp]
    bic.w r0, r0, #0xf0000000
    orr.w r0, r0, #0x70000000
2:  b.w bc250_postcache_map_failure

1:  /* Reproduce the two literal loads replaced at 0xe17c8e. */
    ldr r4, =0xe17d98
    ldr r7, =0xe17fb8
    b.w bc250_postcache_map_loop_setup
    .balign 4, 0
