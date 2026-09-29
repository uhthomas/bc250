/* RAM-only PSP diagnostic: map the first page of the VCN firmware TMR
 * after Linux's first VCPU wait and compare its first four payload words.
 * Map through the signed driver's own read mapping helper, unmap every
 * acquired slot, and never store through the mapped pointer. The unmarked
 * path preserves the proven PSP cache-map/reset sequence.
 * Never flash this interposer ROM view to the BC250 EEPROM.
 */
.syntax unified
.thumb
.arch armv7-a

#ifndef BC250_TMR_PROBE_HI
#define BC250_TMR_PROBE_HI 0x000000f4
#endif
#ifndef BC250_TMR_PROBE_LO
#define BC250_TMR_PROBE_LO 0x1fa00000
#endif
#ifndef BC250_TMR_MAP_ATTR
/* Preserve the original, archived -2 trial unless explicitly overridden. */
#define BC250_TMR_MAP_ATTR 0xfffffffe
#endif

.section .premap_branch, "ax", %progbits
.global bc250_premap_branch
bc250_premap_branch:
    b.w bc250_premap_dispatch

.section .dispatch_cave, "ax", %progbits
.global bc250_premap_dispatch
bc250_premap_dispatch:
    /* The original hook has pushed r4-r7, allocated eight scratch bytes,
     * and verified powered UVD_POWER_STATUS=0x800. Preserve its LR because
     * the map helper is a real BL rather than a leaf SVC call. */
    movs r0, #0
    str r0, [sp]
    ldr r0, =0x1f854         /* shared UVD_SCRATCH1 marker */
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cmp r0, #0
    bne.w unmarked
    ldr r3, [sp]
    ldr r1, =0x5a13c0df
    cmp r3, r1
    bne.w unmarked

    str lr, [sp, #4]        /* spare word in the original eight-byte frame */
    sub sp, #0x28          /* six helper args plus slot and pointer outputs */
    add r0, sp, #0x20
    str r0, [sp, #0x00]    /* pointer-output address */
    movs r0, #0
    str r0, [sp, #0x04]
    str r0, [sp, #0x08]    /* use the read/map SVC 0x6b path */
    str r0, [sp, #0x10]
    str r0, [sp, #0x20]
    ldr r0, =0x0000ffff
    str r0, [sp, #0x0c]
    ldr r0, =BC250_TMR_MAP_ATTR
    str r0, [sp, #0x14]
    movs r0, #0xff
    strb r0, [sp, #0x18]   /* unallocated mapping slot */

    ldr r0, =BC250_TMR_PROBE_HI
    ldr r1, =BC250_TMR_PROBE_LO
    mov.w r2, #0x1000
    add r3, sp, #0x18
    bl bc250_tmr_read_map   /* signed PSP read-mapping helper */
    cmp r0, #0
    bne.w map_failure
    ldr r4, [sp, #0x20]
    cmp r4, #0
    beq.w null_mapping
    ldr r7, =payload_words
    movs r5, #4
    movs r6, #0
next_word:
    ldr r3, [r4], #4
    ldr r0, [r7], #4
    cmp r3, r0
    bne.w mismatch
    adds r6, #1
    subs r5, #1
    bne next_word

    ldr r5, =0x75000004   /* four full-width firmware words matched */
    b.w cleanup
mismatch:
    /* First mismatch index in bits 23:20, observed low 20 bits. */
    ubfx r5, r3, #0, #20
    lsls r6, r6, #20
    orrs r5, r5, r6
    orr.w r5, r5, #0x76000000
    b.w cleanup
map_failure:
    /* Preserve 28 result bits; only the top nibble is the diagnostic tag. */
    ubfx r5, r0, #0, #28
    orr.w r5, r5, #0x70000000
    b.w cleanup
null_mapping:
    ldr r5, =0x78000000
cleanup:
    ldrb r0, [sp, #0x18]
    cmp r0, #0xff
    beq no_slot
    svc #0x6c             /* release the read mapping even on errors */
no_slot:
    mov r0, r5
    add sp, #0x28
    ldr lr, [sp, #4]
    b.w bc250_postcache_map_failure

unmarked:
    ldr r4, =0xe17d98
    ldr r7, =0xe17fb8
    b.w bc250_postcache_map_loop_setup

    .balign 4, 0
payload_words:
    /* Installed navi10_vcn.bin payload at header offset 0x100. */
    .word 0x45574f50, 0x20444552, 0x41205942, 0x0a0d444d
    .ltorg
