addi x2,x2,-752
sw x0,748(x2)
jal x0,208 <_start+0x208>
sw x0,736(x2)
sw x0,732(x2)
lw x15,748(x2)
andi x15,x15,15
addi x14,x0,14
bltu x14,x15,154 <_start+0x154>
slli x14,x15,0x2
addi x15,x0,1648
add x15,x14,x15
lw x15,0(x15)
jalr x0,0(x15)
addi x15,x0,60
sw x15,736(x2)
sw x0,732(x2)
jal x0,168 <_start+0x168>
addi x15,x0,55
sw x15,736(x2)
addi x15,x0,23
sw x15,732(x2)
jal x0,168 <_start+0x168>
addi x15,x0,42
sw x15,736(x2)
addi x15,x0,42
sw x15,732(x2)
jal x0,168 <_start+0x168>
addi x15,x0,23
sw x15,736(x2)
addi x15,x0,55
sw x15,732(x2)
jal x0,168 <_start+0x168>
sw x0,736(x2)
addi x15,x0,60
sw x15,732(x2)
jal x0,168 <_start+0x168>
addi x15,x0,-23
sw x15,736(x2)
addi x15,x0,55
sw x15,732(x2)
jal x0,168 <_start+0x168>
addi x15,x0,-42
sw x15,736(x2)
addi x15,x0,42
sw x15,732(x2)
jal x0,168 <_start+0x168>
addi x15,x0,-55
sw x15,736(x2)
addi x15,x0,23
sw x15,732(x2)
jal x0,168 <_start+0x168>
addi x15,x0,-60
sw x15,736(x2)
sw x0,732(x2)
jal x0,168 <_start+0x168>
addi x15,x0,-55
sw x15,736(x2)
addi x15,x0,-23
sw x15,732(x2)
jal x0,168 <_start+0x168>
addi x15,x0,-42
sw x15,736(x2)
addi x15,x0,-42
sw x15,732(x2)
jal x0,168 <_start+0x168>
addi x15,x0,-23
sw x15,736(x2)
addi x15,x0,-55
sw x15,732(x2)
jal x0,168 <_start+0x168>
sw x0,736(x2)
addi x15,x0,-60
sw x15,732(x2)
jal x0,168 <_start+0x168>
addi x15,x0,23
sw x15,736(x2)
addi x15,x0,-55
sw x15,732(x2)
jal x0,168 <_start+0x168>
addi x15,x0,42
sw x15,736(x2)
addi x15,x0,-42
sw x15,732(x2)
jal x0,168 <_start+0x168>
addi x15,x0,55
sw x15,736(x2)
addi x15,x0,-23
sw x15,732(x2)
addi x0,x0,0
lw x15,736(x2)
addi x15,x15,100
slli x14,x15,0x4
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
sw x14,-228(x15)
lw x15,732(x2)
addi x15,x15,100
slli x14,x15,0x4
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
sw x14,-356(x15)
lw x15,732(x2)
sub x15,x0,x15
srai x14,x15,0x3
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
sw x14,-484(x15)
lw x15,736(x2)
srai x14,x15,0x3
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
sw x14,-612(x15)
lw x15,748(x2)
slli x15,x15,0x2
addi x14,x2,752
add x15,x14,x15
addi x14,x0,1
sw x14,-740(x15)
lw x15,748(x2)
addi x15,x15,1
sw x15,748(x2)
lw x14,748(x2)
addi x15,x0,31
bge x15,x14,c <_start+0xc>
addi x15,x0,3
sw x15,12(x2)
addi x15,x31,0
sw x15,720(x2)
lw x15,720(x2)
sw x15,748(x2)
sw x0,740(x2)
jal x0,5d8 <_start+0x5d8>
sw x0,728(x2)
sw x0,724(x2)
sw x0,744(x2)
jal x0,458 <_start+0x458>
lw x15,744(x2)
slli x15,x15,0x2
addi x14,x2,752
add x15,x14,x15
lw x14,-228(x15)
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
lw x15,-228(x15)
sub x15,x14,x15
sw x15,712(x2)
lw x15,744(x2)
slli x15,x15,0x2
addi x14,x2,752
add x15,x14,x15
lw x14,-356(x15)
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
lw x15,-356(x15)
sub x15,x14,x15
sw x15,708(x2)
lw x15,712(x2)
sw x15,660(x2)
lw x15,660(x2)
bge x0,x15,2bc <_start+0x2bc>
addi x15,x0,1
jal x0,2d0 <_start+0x2d0>
lw x15,660(x2)
bge x15,x0,2cc <_start+0x2cc>
addi x15,x0,-1
jal x0,2d0 <_start+0x2d0>
addi x15,x0,0
sw x15,704(x2)
lw x15,708(x2)
sw x15,664(x2)
lw x15,664(x2)
bge x0,x15,2ec <_start+0x2ec>
addi x15,x0,1
jal x0,300 <_start+0x300>
lw x15,664(x2)
bge x15,x0,2fc <_start+0x2fc>
addi x15,x0,-1
jal x0,300 <_start+0x300>
addi x15,x0,0
sw x15,700(x2)
lw x15,712(x2)
sw x15,676(x2)
lw x15,676(x2)
sw x15,672(x2)
lw x15,672(x2)
bge x15,x0,328 <_start+0x328>
lw x15,672(x2)
sub x15,x0,x15
jal x0,32c <_start+0x32c>
lw x15,672(x2)
sw x15,668(x2)
lw x14,668(x2)
addi x15,x0,511
blt x15,x14,344 <_start+0x344>
addi x15,x0,0
jal x0,374 <_start+0x374>
lw x14,668(x2)
addi x15,x0,1535
blt x15,x14,358 <_start+0x358>
addi x15,x0,1
jal x0,374 <_start+0x374>
lw x14,668(x2)
lui x15,0x1
addi x15,x15,-1537 # 9ff <_start+0x9ff>
blt x15,x14,370 <_start+0x370>
addi x15,x0,2
jal x0,374 <_start+0x374>
addi x15,x0,3
sw x15,696(x2)
lw x15,708(x2)
sw x15,688(x2)
lw x15,688(x2)
sw x15,684(x2)
lw x15,684(x2)
bge x15,x0,39c <_start+0x39c>
lw x15,684(x2)
sub x15,x0,x15
jal x0,3a0 <_start+0x3a0>
lw x15,684(x2)
sw x15,680(x2)
lw x14,680(x2)
addi x15,x0,511
blt x15,x14,3b8 <_start+0x3b8>
addi x15,x0,0
jal x0,3e8 <_start+0x3e8>
lw x14,680(x2)
addi x15,x0,1535
blt x15,x14,3cc <_start+0x3cc>
addi x15,x0,1
jal x0,3e8 <_start+0x3e8>
lw x14,680(x2)
lui x15,0x1
addi x15,x15,-1537 # 9ff <_start+0x9ff>
blt x15,x14,3e4 <_start+0x3e4>
addi x15,x0,2
jal x0,3e8 <_start+0x3e8>
addi x15,x0,3
sw x15,692(x2)
lw x14,704(x2)
lw x15,696(x2)
mul x14,x14,x15
lw x15,744(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
lw x15,-740(x15)
mul x15,x14,x15
lw x14,728(x2)
add x15,x14,x15
sw x15,728(x2)
lw x14,700(x2)
lw x15,692(x2)
mul x14,x14,x15
lw x15,744(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
lw x15,-740(x15)
mul x15,x14,x15
lw x14,724(x2)
add x15,x14,x15
sw x15,724(x2)
lw x15,744(x2)
addi x15,x15,1
sw x15,744(x2)
lw x14,744(x2)
addi x15,x0,31
bge x15,x14,244 <_start+0x244>
lw x15,748(x2)
slli x15,x15,0x2
addi x14,x2,752
add x15,x14,x15
lw x14,-484(x15)
lw x15,728(x2)
add x14,x14,x15
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
sw x14,-484(x15)
lw x15,748(x2)
slli x15,x15,0x2
addi x14,x2,752
add x15,x14,x15
lw x14,-612(x15)
lw x15,724(x2)
add x14,x14,x15
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
sw x14,-612(x15)
lw x15,748(x2)
slli x15,x15,0x2
addi x14,x2,752
add x15,x14,x15
lw x14,-484(x15)
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
lw x15,-484(x15)
srai x15,x15,0x5
sub x14,x14,x15
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
sw x14,-484(x15)
lw x15,748(x2)
slli x15,x15,0x2
addi x14,x2,752
add x15,x14,x15
lw x14,-612(x15)
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
lw x15,-612(x15)
srai x15,x15,0x5
sub x14,x14,x15
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
sw x14,-612(x15)
lw x15,748(x2)
slli x15,x15,0x2
addi x14,x2,752
add x15,x14,x15
lw x14,-228(x15)
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
lw x15,-484(x15)
add x14,x14,x15
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
sw x14,-228(x15)
lw x15,748(x2)
slli x15,x15,0x2
addi x14,x2,752
add x15,x14,x15
lw x14,-356(x15)
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
lw x15,-612(x15)
add x14,x14,x15
lw x15,748(x2)
slli x15,x15,0x2
addi x13,x2,752
add x15,x13,x15
sw x14,-356(x15)
lw x15,740(x2)
addi x15,x15,1
sw x15,740(x2)
lw x14,740(x2)
addi x15,x0,359
bge x15,x14,234 <_start+0x234>
lui x15,0x1
sw x15,716(x2)
lw x15,748(x2)
slli x15,x15,0x2
addi x14,x2,752
add x15,x14,x15
lw x14,-228(x15) # f1c <_start+0xf1c>
lw x15,748(x2)
slli x15,x15,0x1
slli x15,x15,0x2
lw x13,716(x2)
add x15,x13,x15
sw x14,652(x2)
lw x14,652(x2)
srai x14,x14,0x4
sw x14,0(x15)
lw x15,748(x2)
slli x15,x15,0x2
addi x14,x2,752
add x15,x14,x15
lw x14,-356(x15)
lw x15,748(x2)
slli x15,x15,0x1
addi x15,x15,1
slli x15,x15,0x2
lw x13,716(x2)
add x15,x13,x15
sw x14,656(x2)
lw x14,656(x2)
srai x14,x14,0x4
sw x14,0(x15)
addi x15,x0,0
addi x10,x15,0
addi x2,x2,752
jalr x0,0(x1)
