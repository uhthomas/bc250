# SMU queue-3 msg-0x61 direct-store diagnostic, assembled at 0x240.
# Literal 0x230 contains 0x0116f200 (Van Gogh VCN clock-IP enable).
# 0x40 signature and invalid arguments do not touch the target.
# 0x42 stores zero; 0x43 stores one. The target is never read here.
entry a1,0x20
movi a6,0xff
movi a7,-0x1
beqi a2,0x3,@queue_ok
j @finish
queue_ok:
mov.n a10,a2
call8 0x00000ffc
beqi a10,0x40,@signature
movi a5,0x42
beq a10,a5,@write_zero
movi a5,0x43
bne a10,a5,@finish
movi a7,0x1
j @store
write_zero:
movi a7,0x0
store:
l32r a4,0x00000230
memw
s32i a7,a4,0x0
memw
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
