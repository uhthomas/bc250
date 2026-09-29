/* RAM-only experiment: omit the policy-table write of 0x185103 to 0x1f820.
 * The separately patched native type-13 write is already omitted by the
 * input profile. This hook retains every other policy record and SVC call.
 * Never write the resulting ROM view to the BC250 EEPROM.
 */
.syntax unified
.thumb
.arch armv7-a

.section .policy_hook, "ax", %progbits
.global bc250_policy_control_hook
.type bc250_policy_control_hook, %function
bc250_policy_control_hook:
    b.w bc250_policy_control

.section .policy_cave, "ax", %progbits
.global bc250_policy_control
.type bc250_policy_control, %function
bc250_policy_control:
    /* The displaced instructions are SVC #0x7c; ADDS r4, r4, #1. */
    push {r3, r5}
    ldr r3, =0x0001f820
    cmp r0, r3
    bne 1f
    ldr r3, =0x00185103
    cmp r1, r3
    bne 1f
    pop {r3, r5}
    movs r0, #0
    adds r4, r4, #1
    b.w bc250_policy_resume
1:
    pop {r3, r5}
    svc #0x7c
    adds r4, r4, #1
    b.w bc250_policy_resume
