import re
import sys
import os

def parse_mem_operand(op_str):
    """Parses memory operands like '12(x1)' into (12, 'x1')."""
    match = re.match(r'(-?\d+)\s*\(\s*(x\d+)\s*\)', op_str)
    if match:
        return int(match.group(1)), match.group(2)
    raise ValueError(f"Invalid memory operand: {op_str}")

def to_signed_32(val):
    """Helper to treat 32-bit integer as signed for slt/sra ops."""
    val = val & 0xFFFFFFFF
    return val - 0x100000000 if val & 0x80000000 else val

def analyze_multicore_assembly(source_code, num_cores=4):
    print(f"--- Analyzing Program for {num_cores} Cores ---")
    
    # Define explicitly supported instructions based on assembler.py
    SUPPORTED_OPCODES = {
        'nop', 
        'add', 'sub', 'mul', 'and', 'or', 'xor', 'sll', 'srl', 'sra', 'slt', 'sltu',
        'addi', 'andi', 'ori', 'xori', 'slli', 'srli', 'srai', 'slti', 'sltiu',
        'lw', 'sw', 'amoadd.w',
        'beq', 'bne',
        'jalr'
    }

    # 1. Clean code, validate support, and extract labels
    lines = source_code.split('\n')
    instructions = []
    labels = {}
    
    for line in lines:
        code = line.split('#')[0].split('//')[0].strip()
        if not code:
            continue
            
        if ':' in code:
            parts = code.split(':', 1)
            label = parts[0].strip()
            labels[label] = len(instructions)
            inst = parts[1].strip()
            if inst:
                op = inst.replace(',', ' ').split()[0].lower()
                if op not in SUPPORTED_OPCODES:
                    print(f"[FAIL] UNSUPPORTED INSTRUCTION DETECTED: '{inst}'")
                    return False
                instructions.append(inst)
        else:
            op = code.replace(',', ' ').split()[0].lower()
            if op not in SUPPORTED_OPCODES:
                print(f"[FAIL] UNSUPPORTED INSTRUCTION DETECTED: '{code}'")
                return False
            instructions.append(code)

    # 2. Initialize Register Files for all cores
    # x0 is hardwired to 0, x31 is the Core ID
    cores = []
    for i in range(num_cores):
        regs = {f'x{r}': 0 for r in range(32)}
        regs['x31'] = i
        cores.append(regs)

    def get_reg(core, r):
        return 0 if r == 'x0' else core.get(r, 0)

    def set_reg(core, r, val):
        if r != 'x0':
            core[r] = val & 0xFFFFFFFF # Keep it 32-bit unsigned

    # 3. Simulate Execution in Lockstep
    pc = 0
    executed_cycles = 0
    MAX_CYCLES = 10000
    
    # NEW: Shadow Memory to track real values instead of using dummy data!
    memory = {} 
    def read_mem(addr):
        return memory.get((addr // 4) * 4, 0)
    def write_mem(addr, val):
        memory[(addr // 4) * 4] = val & 0xFFFFFFFF

    while pc < len(instructions) and executed_cycles < MAX_CYCLES:
        inst_str = instructions[pc]
        parts = inst_str.replace(',', ' ').split()
        op = parts[0].lower()
        
        # Determine behavior based on Opcode
        if op == 'nop':
            pc += 1
            
        elif op in ['add', 'sub', 'mul', 'sll', 'srl', 'sra', 'and', 'or', 'xor', 'slt', 'sltu']:
            rd, rs1, rs2 = parts[1], parts[2], parts[3]
            for c in range(num_cores):
                v1, v2 = get_reg(cores[c], rs1), get_reg(cores[c], rs2)
                if op == 'add': set_reg(cores[c], rd, v1 + v2)
                elif op == 'sub': set_reg(cores[c], rd, v1 - v2)
                elif op == 'mul': set_reg(cores[c], rd, v1 * v2)
                elif op == 'and': set_reg(cores[c], rd, v1 & v2)
                elif op == 'or':  set_reg(cores[c], rd, v1 | v2)
                elif op == 'xor': set_reg(cores[c], rd, v1 ^ v2)
                elif op == 'sll': set_reg(cores[c], rd, v1 << (v2 & 0x1F))
                elif op == 'srl': set_reg(cores[c], rd, v1 >> (v2 & 0x1F))
                elif op == 'sra': set_reg(cores[c], rd, to_signed_32(v1) >> (v2 & 0x1F))
                elif op == 'slt': set_reg(cores[c], rd, 1 if to_signed_32(v1) < to_signed_32(v2) else 0)
                elif op == 'sltu': set_reg(cores[c], rd, 1 if v1 < v2 else 0)
            pc += 1

        elif op in ['addi', 'andi', 'ori', 'xori', 'slli', 'srli', 'srai', 'slti', 'sltiu']:
            rd, rs1, imm = parts[1], parts[2], int(parts[3])
            for c in range(num_cores):
                v1 = get_reg(cores[c], rs1)
                if op == 'addi': set_reg(cores[c], rd, v1 + imm)
                elif op == 'andi': set_reg(cores[c], rd, v1 & imm)
                elif op == 'ori':  set_reg(cores[c], rd, v1 | imm)
                elif op == 'xori': set_reg(cores[c], rd, v1 ^ imm)
                elif op == 'slli': set_reg(cores[c], rd, v1 << (imm & 0x1F))
                elif op == 'srli': set_reg(cores[c], rd, v1 >> (imm & 0x1F))
                elif op == 'srai': set_reg(cores[c], rd, to_signed_32(v1) >> (imm & 0x1F))
                elif op == 'slti': set_reg(cores[c], rd, 1 if to_signed_32(v1) < imm else 0)
                elif op == 'sltiu': set_reg(cores[c], rd, 1 if v1 < (imm & 0xFFFFFFFF) else 0)
            pc += 1

        elif op == 'lw':
            rd = parts[1]
            imm, rs1 = parse_mem_operand(parts[2])
            for c in range(num_cores):
                addr = get_reg(cores[c], rs1) + imm
                set_reg(cores[c], rd, read_mem(addr))
            pc += 1

        elif op == 'sw':
            rs2 = parts[1]
            imm, rs1 = parse_mem_operand(parts[2])
            for c in range(num_cores):
                addr = get_reg(cores[c], rs1) + imm
                val = get_reg(cores[c], rs2)
                write_mem(addr, val)
            pc += 1

        elif op == 'amoadd.w':
            rd = parts[1]
            rs2 = parts[2]                            # <-- FIX: Added this line to extract rs2!
            rs1_idx = re.sub(r'[^0-9]', '', parts[3])
            rs1 = f"x{rs1_idx}"
            
            # PERFECT SIMULATION: Read the old value, give it to the core, 
            # and write the incremented value back to memory!
            for c in range(num_cores):
                addr = get_reg(cores[c], rs1)
                addend = get_reg(cores[c], rs2)       # Now rs2 exists here!
                
                old_val = read_mem(addr)
                set_reg(cores[c], rd, old_val)
                write_mem(addr, old_val + addend)
            pc += 1

        elif op in ['beq', 'bne']:
            rs1, rs2, target = parts[1], parts[2], parts[3]
            
            # Check for Divergence
            decisions = []
            for c in range(num_cores):
                v1, v2 = get_reg(cores[c], rs1), get_reg(cores[c], rs2)
                if op == 'beq': decisions.append(v1 == v2)
                elif op == 'bne': decisions.append(v1 != v2)
                
            if len(set(decisions)) != 1:
                print(f"[FAIL] DIVERGENCE DETECTED at PC {pc}: '{inst_str}'")
                print(f"       Branch decisions across cores: {decisions}")
                return False
                
            # If all agree, take the branch or fall through
            if decisions[0]: 
                pc = labels[target] if target in labels else pc + (int(target) // 4)
            else:
                pc += 1

        elif op == 'jalr':
            pc += 1

        else:
            # Should never reach here because of Pass 1 validation, but safe fallback
            pc += 1

        executed_cycles += 1

    if executed_cycles >= MAX_CYCLES:
        print("[WARNING] Max simulation cycles reached. Infinite loop?")
        return False
        
    print("[PASS] Program is safe for multi-core lockstep execution!")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 multicore_checker.py <path_to_assembly_file> [num_cores]")
        sys.exit(1)

    file_path = sys.argv[1]
    
    # Default to 4 cores, unless specified as the second argument
    num_cores = 4
    if len(sys.argv) >= 3:
        try:
            num_cores = int(sys.argv[2])
        except ValueError:
            print(f"[WARNING] Invalid number of cores '{sys.argv[2]}'. Defaulting to 4.")

    if not os.path.exists(file_path):
        print(f"[ERROR] File not found: {file_path}")
        sys.exit(1)

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source_code = f.read()
    except Exception as e:
        print(f"[ERROR] Could not read file {file_path}: {e}")
        sys.exit(1)

    analyze_multicore_assembly(source_code, num_cores=num_cores)