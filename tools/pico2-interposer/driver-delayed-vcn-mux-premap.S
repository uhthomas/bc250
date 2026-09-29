/* RAM-only PSP diagnostic: compare the VCPU memory-controller muxes after
 * Linux's first VCPU wait and before the signed driver replays cache maps.
 * Linux programs all three muxes before it releases VCPU reset. A full-width
 * mismatch identifies the first register that did not retain that value.
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
    /* The original hook has pushed r4-r7, allocated eight scratch bytes,
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

    ldr r4, =mux_addresses
    ldr r7, =mux_values
    movs r5, #3
    movs r6, #0
next_mux:
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
    bne next_mux

    ldr r0, =0x72000003   /* three muxes matched, all 32 bits */
    b.w finish
mismatch:
    /* First mismatch index in bits 23:20, observed low 20 bits. */
    ubfx r0, r3, #0, #20
    lsls r6, r6, #20
    orrs r0, r0, r6
    orr.w r0, r0, #0x73000000
finish:
    b.w bc250_postcache_map_failure

unmarked:
    /* Reproduce the two literal loads replaced at 0xe17c8e. */
    ldr r4, =0xe17d98
    ldr r7, =0xe17fb8
    b.w bc250_postcache_map_loop_setup

    .balign 4, 0
mux_addresses:
    .word 0x200e4, 0x200ec, 0x200f4
mux_values:
    .word 0x040c2040, 0x040c2040, 0x00000088
    .ltorg
