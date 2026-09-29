/* RAM-only PSP diagnostic: test one reversible write to the candidate
 * fabric word, guarded by an exact original 0xF0 read. The signed driver
 * returns the post-write value only after restoring 0xF0 and reading it back.
 * No BIOS EEPROM or Pico flash write is permitted.
 */
.syntax unified
.thumb
.arch armv7-a

.section .map_cave, "ax", %progbits
.global bc250_fabric_bit_probe
.type bc250_fabric_bit_probe, %function
bc250_fabric_bit_probe:
    sub sp, #16
    movs r0, #0
    str r0, [sp]
    ldr r0, =0x00050d6c
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, return_result
    ldr r0, [sp]
    cmp.w r0, #0xf0
    bne encode_result

    /* Test only bit 11 of the value just measured; no unrelated bits. */
    ldr r0, =0x00050d6c
    ldr r1, =0x000008f0
    movs r2, #4
    svc #0x7c
    str r0, [sp, #4]

    movs r0, #0
    str r0, [sp]
    ldr r0, =0x00050d6c
    mov r1, sp
    movs r2, #4
    svc #0x7b
    str r0, [sp, #8]
    ldr r0, [sp]
    str r0, [sp, #12]

    /* Restore even when either experimental service reported an error. */
    ldr r0, =0x00050d6c
    mov.w r1, #0xf0
    movs r2, #4
    svc #0x7c
    cbnz r0, restore_failed
    movs r0, #0
    str r0, [sp]
    ldr r0, =0x00050d6c
    mov r1, sp
    movs r2, #4
    svc #0x7b
    cbnz r0, restore_failed
    ldr r0, [sp]
    cmp.w r0, #0xf0
    bne restore_failed

    ldr r0, [sp, #4]
    cbnz r0, return_result
    ldr r0, [sp, #8]
    cbnz r0, return_result
    ldr r0, [sp, #12]
encode_result:
    bic.w r0, r0, #0xf0000000
    orr.w r0, r0, #0x70000000
return_result:
    add sp, #16
    b.w bc250_postload_readback_failure
restore_failed:
    ldr r0, =0x7f000000
    b return_result
    .balign 4, 0
