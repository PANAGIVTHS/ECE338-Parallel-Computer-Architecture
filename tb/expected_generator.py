import re
import argparse
from pathlib import Path

# Memory configurations
MEM_DEPTH = 1024
REG_DEPTH = 32

def parse_register(reg_str):
    """Extracts the integer index from a register string like 'x1', 'x31'"""
    return int(reg_str.replace('x', '').replace(',', ''))

def format_hex(val):
    """Formats an integer into an 8-character 32-bit hex string"""
    # Force the value into a 32-bit unsigned integer range
    val_32bit = val & 0xFFFFFFFF
    return f"{val_32bit:08x}"

def generate_expected_memories(asm_text, num_cores=2):
    # Global shared data memory
    memory = [0] * MEM_DEPTH
    
    # 2D Array for register files (one list of 32 registers per core)
    regfiles = [[0] * REG_DEPTH for _ in range(num_cores)]

    instructions = []
    labels = {}

    # PASS 1: Extract instructions and resolve labels
    for line in asm_text.splitlines():
        code = line.split('#')[0].split('//')[0].strip()
        if not code:
            continue
            
        # Check if line contains a label (e.g., "skip1:" or "end: beq x0, x0, end")
        if ':' in code:
            parts = code.split(':', 1)
            label_name = parts[0].strip()
            # Record the label pointing to the NEXT instruction index
            labels[label_name] = len(instructions) 
            
            # If there's an instruction on the same line after the colon, add it
            inst_part = parts[1].strip()
            if inst_part:
                instructions.append(inst_part)
        else:
            instructions.append(code)

    # PASS 2: Simulate execution for each core
    for core_id in range(num_cores):
        registers = regfiles[core_id]
        registers[31] = core_id  # Hardwire x31 to CORE_ID
        
        pc = 0
        cycles = 0
        max_cycles = 10000 # Safeguard against complex infinite loops
        
        while pc < len(instructions) and cycles < max_cycles:
            cycles += 1
            inst = instructions[pc]
            # Split by whitespace, ignoring multiple spaces and commas
            parts = [p.strip(',') for p in inst.split()]
            op = parts[0].lower()

            if op == 'nop':
                pass
                
            elif op == 'add':
                rd = parse_register(parts[1])
                rs1 = parse_register(parts[2])
                rs2 = parse_register(parts[3])
                if rd != 0 and rd != 31:
                    registers[rd] = registers[rs1] + registers[rs2]
                    
            elif op == 'sub':
                rd = parse_register(parts[1])
                rs1 = parse_register(parts[2])
                rs2 = parse_register(parts[3])
                if rd != 0 and rd != 31:
                    registers[rd] = registers[rs1] - registers[rs2]

            elif op == 'add':
                rd = parse_register(parts[1])
                rs1 = parse_register(parts[2])
                rs2 = parse_register(parts[3])
                if rd != 0 and rd != 31:
                    registers[rd] = registers[rs1] + registers[rs2]
                    
            elif op == 'mul':
                rd = parse_register(parts[1])
                rs1 = parse_register(parts[2])
                rs2 = parse_register(parts[3])
                if rd != 0 and rd != 31:
                    # Multiply and mask to 32-bit just like hardware
                    registers[rd] = (registers[rs1] * registers[rs2]) & 0xFFFFFFFF
                    
            elif op == 'addi':
                rd = parse_register(parts[1])
                rs1 = parse_register(parts[2])
                imm = int(parts[3])
                if rd != 0 and rd != 31:
                    registers[rd] = registers[rs1] + imm
            
            elif op == 'lw' or op == 'sw':
                # Parse format like: lw x4, -12(x8)
                reg_a = parse_register(parts[1])
                match = re.match(r'(-?\d+)\s*\(\s*(x\d+)\s*\)', parts[2])
                if not match:
                    raise ValueError(f"Failed to parse memory offset in: {inst}")
                
                imm = int(match.group(1))
                base_reg = parse_register(match.group(2))
                
                # Calculate byte address, convert to word index
                byte_addr = registers[base_reg] + imm
                word_idx = (byte_addr & 0xFFFFFFFF) // 4
                
                if op == 'lw':
                    if reg_a != 0 and reg_a != 31:
                        if 0 <= word_idx < MEM_DEPTH:
                            registers[reg_a] = memory[word_idx]
                        else:
                            registers[reg_a] = 0 # Out of bounds read
                elif op == 'sw':
                    if 0 <= word_idx < MEM_DEPTH:
                        memory[word_idx] = registers[reg_a]
                        
            elif op == 'beq':
                rs1 = parse_register(parts[1])
                rs2 = parse_register(parts[2])
                target = parts[3]
                
                if registers[rs1] == registers[rs2]:
                    # Determine target PC (support both Labels and Integer offsets)
                    if target in labels:
                        target_pc = labels[target]
                    else:
                        imm = int(target)
                        target_pc = pc + (imm // 4)
                        
                    # Trap logic: Break simulation if jumping to the exact same instruction
                    if target_pc == pc:
                        break
                        
                    # -1 because the loop unconditionally does pc += 1 at the end
                    pc = target_pc - 1 

            pc += 1

    return regfiles, memory

def main():
    # Set this to match your Verilog NUM_CORES parameter
    num_cores = 2 
    
    current_dir = Path('.')
    asm_files = []
    
    # 1. Glob only 1 level deep for folders starting with "test"
    for path in current_dir.glob('test*/program.asm'):
        # 2. STRICT MATCH: Ensure folder name is exactly "test" + digits (e.g., test1, test12)
        if re.fullmatch(r'test\d+', path.parent.name):
            asm_files.append(path)

    # Sort files numerically based on the test number (optional but helpful)
    asm_files.sort(key=lambda p: int(p.parent.name.replace('test', '')))

    if not asm_files:
        print("No 'program.asm' files found in strict 'test[number]' directories.")
        return

    print(f"Found {len(asm_files)} tests. Generating expected memories for {num_cores} cores...\n")

    for asm_path in asm_files:
        test_dir = asm_path.parent
        print(f"Processing: {asm_path}")

        try:
            with open(asm_path, 'r', encoding='utf-8') as f:
                asm_code = f.read()
        except Exception as e:
            print(f"  [Error] Failed to read {asm_path}: {e}")
            continue

        # Run simulation
        regfiles, memory = generate_expected_memories(asm_code, num_cores)

        # Output regfiles into the specific test directory
        for core_id in range(num_cores):
            reg_filename = test_dir / f"regfile_c{core_id}.mem"
            with open(reg_filename, 'w') as f:
                for val in regfiles[core_id]:
                    f.write(format_hex(val) + "\n")
            print(f"  -> Generated {reg_filename.name}")

        # Output shared data memory into the specific test directory
        data_filename = test_dir / "data.mem"
        with open(data_filename, 'w') as f:
            for val in memory:
                f.write(format_hex(val) + "\n")
        print(f"  -> Generated {data_filename.name}\n")

    print("Expected memory generation complete!")

if __name__ == "__main__":
    main()