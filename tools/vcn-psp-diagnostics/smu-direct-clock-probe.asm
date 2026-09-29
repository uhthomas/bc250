# SMU queue-3 msg-0x61 diagnostic, assembled at 0x240.
# Literal 0x230 contains 0x0116f200 (Van Gogh VCN clock-IP enable).
# 0x40 returns the existing signature without touching hardware.
# 0x41 performs exactly one direct SMU-core load and returns the full word.
# Other arguments and queues are rejected. No hardware stores occur.
entry a1,0x20
movi a6,0xff
movi a7,-0x1
beqi a2,0x3,@queue_ok
j @finish
queue_ok:
mov.n a10,a2
call8 0x00000ffc
beqi a10,0x40,@signature
movi a5,0x41
bne a10,a5,@finish
l32r a4,0x00000230
memw
l32i a7,a4,0x0
movi a6,0x1
j @finish
signature:
movi a7,0x250
slli a7,a7,0x10
addi a7,a7,0x16
movi a6,0x1
finish:
mov.n a10,a2
mov.n a11,a7
call8 0x00000fe4
mov.n a10,a2
mov.n a11,a6
call8 0x00000fa8
retw.n
