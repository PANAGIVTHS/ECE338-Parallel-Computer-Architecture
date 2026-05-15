import re
import sys
import os

def parse_mem_operand(op_str):
    """Parses memory operands like '12(x1)' into (12, 'x1')."""
    match = re.match(r'(-?\d+)\s*\(\s*(x\d+)\s*\)', op_str)
    if match:
        return int(match.group(1)), match.group(2)
    raise ValueError(f"Invalid memory operand: {op_str}")

def analyze_multicore_assembly(source_code, num_cores=4):
    print(f"--- Analyzing Program for {num_cores} Cores ---")
    
    # 1. Clean code and extract labels
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
                instructions.append(inst)
        else:
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

    while pc < len(instructions) and executed_cycles < MAX_CYCLES:
        inst_str = instructions[pc]
        parts = inst_str.replace(',', ' ').split()
        op = parts[0].lower()
        
        # Determine behavior based on Opcode
        if op == 'nop':
            pc += 1
            
        elif op in ['add', 'sub', 'sll', 'srl', 'sra', 'and', 'or', 'xor', 'slt', 'sltu']:
            rd, rs1, rs2 = parts[1], parts[2], parts[3]
            for c in range(num_cores):
                v1, v2 = get_reg(cores[c], rs1), get_reg(cores[c], rs2)
                if op == 'add': set_reg(cores[c], rd, v1 + v2)
                elif op == 'sub': set_reg(cores[c], rd, v1 - v2)
                elif op == 'sll': set_reg(cores[c], rd, v1 << (v2 & 0x1F))
            pc += 1

        elif op in ['addi', 'slli', 'srli', 'srai', 'andi', 'ori', 'xori', 'slti']:
            rd, rs1, imm = parts[1], parts[2], int(parts[3])
            for c in range(num_cores):
                v1 = get_reg(cores[c], rs1)
                if op == 'addi': set_reg(cores[c], rd, v1 + imm)
                elif op == 'slli': set_reg(cores[c], rd, v1 << (imm & 0x1F))
            pc += 1

        elif op == 'lw':
            rd = parts[1]
            imm, rs1 = parse_mem_operand(parts[2])
            for c in range(num_cores):
                # We don't actually load memory in this safety checker, 
                # we just simulate the register state ignoring memory contents
                set_reg(cores[c], rd, 0)
            pc += 1

        elif op == 'sw':
            rs2 = parts[1]
            imm, rs1 = parse_mem_operand(parts[2])
            
            # Extract the absolute memory addresses requested by all cores
            target_addresses = []
            for c in range(num_cores):
                addr = get_reg(cores[c], rs1) + imm
                target_addresses.append(addr)
                
            # Check for Corruption (Duplicates in the requested addresses)
            if len(set(target_addresses)) != len(target_addresses):
                print(f"[FAIL] MEMORY CORRUPTION DETECTED at PC {pc}: '{inst_str}'")
                print(f"       Computed Addresses: {target_addresses}")
                return False
                
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
            rd = parts[1]
            imm, rs1 = parse_mem_operand(parts[2])
            
            # Check for Divergence
            target_pcs = []
            for c in range(num_cores):
                target_pcs.append(get_reg(cores[c], rs1) + imm)
                set_reg(cores[c], rd, (pc + 1) * 4)
                
            if len(set(target_pcs)) != 1:
                print(f"[FAIL] DIVERGENCE DETECTED at PC {pc}: '{inst_str}'")
                print(f"       Target PCs across cores: {target_pcs}")
                return False
                
            # Treat jalr x0, 0(x1) returning to 0 as an exit condition
            if target_pcs[0] == 0:
                break
                
            pc = target_pcs[0] // 4

        else:
            pc += 1 # Ignore unknown instructions

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