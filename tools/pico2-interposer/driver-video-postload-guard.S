/* Surface both type-13 post-load reset service failures to the PSP caller.
 * The stock function ignores the 0x0900c004 result and the 0x1f8a4 helper
 * forces a zero return. Keep the original success continuation and cleanup.
 * RAM-only interposer patch; NEVER write to the BC250 BIOS EEPROM.
 */
.syntax unified
.thumb
.arch armv7-a

.section .postload_hook, "ax", %progbits
.global bc250_postload_hook
.type bc250_postload_hook, %function
bc250_postload_hook:
    b.w bc250_postload_guard

.section .postload_cave, "ax", %progbits
.global bc250_postload_guard
.type bc250_postload_guard, %function
bc250_postload_guard:
    /* The first SVC executes only for physical-function context 0xffff.
     * Other contexts reach the hook with their context value in r0.
     */
    ldr r1, [sp, #0x14]
    movw r2, #0xffff
    cmp r1, r2
    bne 1f
    cbnz r0, 2f
1:
    ldr r0, =0x1f8a4
    movs r1, #1
    movs r2, #4
    svc #0x7c
    cbnz r0, 2f
    b.w bc250_postload_success
2:
    /* Mirror the original nonzero helper path at e0fd02: return directly,
     * without setting the firmware-loaded flag or mapping metadata.
     */
    b.w bc250_postload_failure
    .balign 4, 0
