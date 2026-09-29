/* RAM-only PSP diagnostic: compare the sixteen VCPU cache-window words
 * after Linux's first VCPU wait, before any second-call cache-map replay.
 * The seventeenth word, GFX10_ADDR_CONFIG, has a documented masked bit and
 * is deliberately excluded. The unmarked path preserves the proven load.
 * Never flash this interposer ROM view to the BC250 EEPROM.
 */
.syntax unified
.thumb
.arch armv7-a

.section .premap_branch, "ax", %progbits
.global bc250_premap_branch
bc250_premap_branch:
    b.w bc250_premap_dispatch

.section .dispatch_cave, "ax", %progbits
.global bc250_premap_dispatch
bc250_premap_dispatch:
    /* The original hook has already pushed r4-r7, allocated eight bytes,
     * and verified powered UVD_POWER_STATUS=0x800. */
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

    /* Marked request: read each window, without writing or replaying any. */
    ldr r4, =0xe17d98      /* original address table */
    ldr r7, =0xe17fb8      /* original programmed values */
    movs r5, #16
    movs r6, #0            /* zero-based index */
next_window:
    movs r0, #0
    str r0, [sp]
    ldr r0, [r4], #4
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cmp r0, #0
    bne.w finish
    ldr r3, [sp]
    ldr r0, [r7], #4
    cmp r3, r0
    bne.w mismatch
    adds r6, #1
    subs r5, #1
    bne next_window

    ldr r0, =0x70000010   /* all sixteen values matched, full 32 bits */
    b.w finish
mismatch:
    /* Encoded first mismatch: index in bits 23:20, observed low 20 bits.
     * Comparison itself is full 32-bit; the status is only a locator. */
    ubfx r0, r3, #0, #20
    lsls r6, r6, #20
    orrs r0, r0, r6
    orr.w r0, r0, #0x71000000
finish:
    b.w bc250_postcache_map_failure

unmarked:
    /* Reproduce the two literal loads replaced at 0xe17c8e. */
    ldr r4, =0xe17d98
    ldr r7, =0xe17fb8
    b.w bc250_postcache_map_loop_setup
    .balign 4, 0
