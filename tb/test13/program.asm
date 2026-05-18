# =========================================================================
# N-BODY GRAVITY KERNEL (4-CORE SIMT GPU)
# Memory Tape Mode: Saves all 102 frames consecutively!
# Frame Stride: 80 Bytes. Body Stride: 20 Bytes.
# STABILIZATION: Features a hardware softening parameter to prevent explosion!
# =========================================================================

kernel_start:
    # --- BOOTLOADER: Initialize Frame 0 (Addresses 0-79) ---
    # Body 0 (Core 0 Offset: 0)
    addi x5, x0, 10
    sw x5, 16(x0)     # Mass = 10
    addi x5, x0, 100
    sw x5, 0(x0)      # X = 100
    sw x5, 4(x0)      # Y = 100
    
    # Body 1 (Core 1 Offset: 20)
    addi x5, x0, 10
    sw x5, 36(x0)     # Mass = 10
    addi x5, x0, 150
    sw x5, 20(x0)     # X = 150
    sw x5, 24(x0)     # Y = 150
    addi x5, x0, 5
    sw x5, 32(x0)     # VY = 5
    
    # Body 2 (Core 2 Offset: 40)
    addi x5, x0, 10
    sw x5, 56(x0)     # Mass = 10
    addi x5, x0, 50
    sw x5, 40(x0)     # X = 50
    sw x5, 44(x0)     # Y = 50
    addi x5, x0, -5
    sw x5, 48(x0)     # VX = -5

    # Body 3 (Core 3 Offset: 60)
    addi x5, x0, 10
    sw x5, 76(x0)     # Mass = 10
    addi x5, x0, 100
    sw x5, 60(x0)     # X = 100
    addi x5, x0, 50
    sw x5, 64(x0)     # Y = 50
    addi x5, x0, 5
    sw x5, 68(x0)     # VX = 5
    addi x5, x0, -5
    sw x5, 72(x0)     # VY = -5
    # --- END BOOTLOADER ---

    addi x4, x0, 50       # SET NUMBER OF FRAMES HERE <-----------------------------------------------------
    addi x1, x0, 0        # x1 = GLOBAL FRAME READ OFFSET (Starts at 0)

frame_loop:
    # 1. Setup Core Read Pointers (x30)
    slli x30, x31, 4      # x30 = Core_ID * 16
    slli x29, x31, 2      # x29 = Core_ID * 4
    add x30, x30, x29     # x30 = Core_ID * 20
    add x30, x30, x1      # Add the Global Frame Offset!
    
    lw x29, 0(x30)        # x29 = X_my
    lw x28, 4(x30)        # x28 = Y_my
    
    addi x27, x0, 0       # fx_total = 0
    addi x26, x0, 0       # fy_total = 0
    addi x25, x0, 0       # j = 0

nbody_loop:
    # 2. Branchless Mask: is_valid = (i != j) ? 1 : 0
    sub x12, x31, x25     
    sltu x16, x0, x12     
    
    # Target Address Offset (x24)
    slli x24, x25, 4      
    slli x12, x25, 2      
    add x24, x24, x12     
    add x24, x24, x1      # Add the Global Frame Offset!
    
    # 3. Load Target Body Data
    lw x23, 0(x24)        
    lw x22, 4(x24)        
    
    # 4. Distance Calculation
    sub x21, x23, x29     # dx
    sub x20, x22, x28     # dy
    
    mul x19, x21, x21     # dx^2
    mul x18, x20, x20     # dy^2
    add x19, x19, x18     # x19 = dist_sq = dx^2 + dy^2
    
    # =====================================================================
    # SOFTENING PARAMETER ACTIVATION
    # Add an epsilon value (e.g., 25) to dist_sq to prevent div-by-zero or 
    # astronomical force spikes when objects pass dangerously close.
    # =====================================================================
    addi x19, x19, 25     # dist_sq_softened = dist_sq + 25
    
    # 5. Call Integer Square Root (Input x10 = dist_sq_softened)
    addi x10, x19, 0      
    beq x0, x0, sqrt_16bit
ret_sqrt_1:
    addi x18, x10, 0      # x18 = dist_softened
    
    # 6. Calculate scaled r^3
    mul x17, x19, x18     # r_cubed = dist_sq_softened * dist_softened
    srli x17, x17, 6      # x17 = r_cubed_scaled = r_cubed >> 6
    
    # Prevent Div-by-Zero (Double protection fallback)
    sltu x12, x0, x17     
    addi x13, x0, 1
    sub x13, x13, x12     
    add x17, x17, x13     
    
    # 7. Force Magnitude
    lw x14, 16(x30)       # Mass_my
    lw x15, 16(x24)       # Mass_other
    mul x14, x14, x15
    addi x15, x0, 10      # G_CONST = 10
    mul x14, x14, x15     # x14 = force_mag
    
    # ==========================================
    # 8. Calculate FX Component
    # ==========================================
    slt x12, x21, x0      
    slli x12, x12, 1      
    addi x13, x0, 1
    sub x12, x13, x12     # sign_x
    mul x13, x21, x12     # abs(dx)
    
    mul x10, x14, x13     
    addi x11, x17, 0      
    
    addi x2, x0, 1
    beq x0, x0, div_unsigned
ret_div_1:
    
    mul x10, x10, x16     
    mul x10, x10, x12     
    add x27, x27, x10     
    
    # ==========================================
    # 9. Calculate FY Component
    # ==========================================
    slt x12, x20, x0      
    slli x12, x12, 1
    addi x13, x0, 1
    sub x12, x13, x12     # sign_y
    mul x13, x20, x12     # abs(dy)
    
    mul x10, x14, x13     
    addi x11, x17, 0      
    
    addi x2, x0, 2
    beq x0, x0, div_unsigned
ret_div_2:
    
    mul x10, x10, x16      
    mul x10, x10, x12     
    add x26, x26, x10     

    # 10. Inner Loop Control
    addi x25, x25, 1
    addi x12, x0, 4       
    
    beq x25, x12, skip_inner
    beq x0, x0, nbody_loop
skip_inner:

    # ==========================================
    # 11. Velocity & Position Integration 
    # ==========================================
    lw x21, 8(x30)        # VX_my
    
    # Divide FX by Mass
    slt x12, x27, x0      
    slli x12, x12, 1
    addi x13, x0, 1
    sub x12, x13, x12     
    mul x10, x27, x12     
    lw x11, 16(x30)       
    
    addi x2, x0, 3
    beq x0, x0, div_unsigned
ret_div_3:
    
    # Write Base = Read Base + 80
    mul x10, x10, x12     # ax
    add x21, x21, x10     # VX += ax
    sw x21, 88(x30)       # Store VX to NEW frame!
    add x29, x29, x21     # X += VX
    sw x29, 80(x30)       # Store X to NEW frame!
    
    # Divide FY by Mass
    lw x20, 12(x30)       
    slt x12, x26, x0      
    slli x12, x12, 1
    addi x13, x0, 1
    sub x12, x13, x12     
    mul x10, x26, x12     
    
    addi x2, x0, 4
    beq x0, x0, div_unsigned
ret_div_4:

    mul x10, x10, x12     # ay
    add x20, x20, x10     # VY += ay
    sw x20, 92(x30)       # Store VY to NEW frame!
    add x28, x28, x20     # Y += VY
    sw x28, 84(x30)       # Store Y to NEW frame!

    # Copy Mass to the new frame so it isn't lost
    lw x12, 16(x30)
    sw x12, 96(x30)       

    # Outer Loop Control (Frames)
    addi x1, x1, 80       # Advance Global Read Offset by 80 bytes for the next frame!
    addi x4, x4, -1
    
    beq x4, x0, skip_outer
    beq x0, x0, frame_loop
skip_outer:

    # END OF KERNEL
program_exit:
    jalr x0, 0(x0)

# =========================================================================
# HARDWARE MATH MACROS
# =========================================================================

sqrt_16bit:
    addi x5, x0, 0        
    addi x6, x0, 1
    slli x6, x6, 14       
sqrt_loop:
    add x7, x5, x6        
    sltu x8, x10, x7      
    addi x8, x8, -1       
    and x9, x7, x8
    sub x10, x10, x9      
    srli x5, x5, 1
    and x9, x6, x8
    add x5, x5, x9        
    srli x6, x6, 2
    beq x6, x0, skip_sqrt_loop
    beq x0, x0, sqrt_loop
skip_sqrt_loop:
    addi x10, x5, 0       
    beq x0, x0, ret_sqrt_1

div_unsigned:
    addi x5, x0, 0        
    addi x6, x0, 0        
    addi x7, x0, 16       
div_loop:
    addi x7, x7, -1       
    slli x6, x6, 1        
    srl x8, x10, x7       
    andi x8, x8, 1        
    or x6, x6, x8         
    sltu x8, x6, x11      
    addi x8, x8, -1       
    and x9, x11, x8       
    sub x6, x6, x9        
    addi x9, x0, 1
    sll x9, x9, x7        
    and x9, x9, x8        
    or x5, x5, x9         
    beq x7, x0, skip_div_loop
    beq x0, x0, div_loop
skip_div_loop:
    addi x10, x5, 0       
    addi x3, x0, 1
    beq x2, x3, ret_div_1
    addi x3, x0, 2
    beq x2, x3, ret_div_2
    addi x3, x0, 3
    beq x2, x3, ret_div_3
    addi x3, x0, 4
    beq x2, x3, ret_div_4