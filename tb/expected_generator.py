import re
import argparse
import sys
from pathlib import Path

# Memory configurations
MEM_DEPTH = 2048
REG_DEPTH = 32
NUM_CORES = 2
STACK_P_INIT = 0

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
        registers[2] = STACK_P_INIT

        pc = 0
        cycles = 0
        max_cycles = 10000 # Safeguard against complex infinite loops
        
        while pc < len(instructions) and cycles < max_cycles:
            cycles += 1
            inst = instructions[pc]
            # Replace commas with spaces FIRST, then split by whitespace
            parts = inst.replace(',', ' ').split()
            op = parts[0].lower()

            if op == 'nop':
                pass
                
            elif op in ['add', 'sub', 'mul', 'and', 'or', 'sll', 'srl', 'sra', 'slt', 'sltu']:
                rd = parse_register(parts[1])
                rs1 = parse_register(parts[2])
                rs2 = parse_register(parts[3])
                if rd != 0 and rd != 31:
                    v1 = registers[rs1]
                    v2 = registers[rs2]
                    
                    if op == 'add':
                        registers[rd] = (v1 + v2) & 0xFFFFFFFF
                    elif op == 'sub':
                        registers[rd] = (v1 - v2) & 0xFFFFFFFF
                    elif op == 'mul':
                        registers[rd] = (v1 * v2) & 0xFFFFFFFF
                    elif op == 'and':
                        registers[rd] = v1 & v2
                    elif op == 'or':
                        registers[rd] = v1 | v2
                    elif op == 'sll':
                        registers[rd] = (v1 << (v2 & 0x1F)) & 0xFFFFFFFF
                    elif op == 'srl':
                        registers[rd] = (v1 >> (v2 & 0x1F)) & 0xFFFFFFFF
                    elif op == 'sra':
                        # Convert to signed 32-bit integer for arithmetic shift
                        sv1 = v1 if v1 < 0x80000000 else v1 - 0x100000000
                        registers[rd] = (sv1 >> (v2 & 0x1F)) & 0xFFFFFFFF
                    elif op == 'slt':
                        sv1 = v1 if v1 < 0x80000000 else v1 - 0x100000000
                        sv2 = v2 if v2 < 0x80000000 else v2 - 0x100000000
                        registers[rd] = 1 if sv1 < sv2 else 0
                    elif op == 'sltu':
                        registers[rd] = 1 if v1 < v2 else 0
                        
            elif op in ['addi', 'andi', 'slli', 'srli', 'srai', 'slti', 'sltiu']:
                rd = parse_register(parts[1])
                rs1 = parse_register(parts[2])
                imm = int(parts[3])
                if rd != 0 and rd != 31:
                    v1 = registers[rs1]
                    
                    if op == 'addi':
                        registers[rd] = (v1 + imm) & 0xFFFFFFFF
                    elif op == 'andi':
                        registers[rd] = (v1 & imm) & 0xFFFFFFFF
                    elif op == 'slli':
                        registers[rd] = (v1 << (imm & 0x1F)) & 0xFFFFFFFF
                    elif op == 'srli':
                        registers[rd] = (v1 >> (imm & 0x1F)) & 0xFFFFFFFF
                    elif op == 'srai':
                        sv1 = v1 if v1 < 0x80000000 else v1 - 0x100000000
                        registers[rd] = (sv1 >> (imm & 0x1F)) & 0xFFFFFFFF
                    elif op == 'slti':
                        sv1 = v1 if v1 < 0x80000000 else v1 - 0x100000000
                        registers[rd] = 1 if sv1 < imm else 0
                    elif op == 'sltiu':
                        u_imm = imm & 0xFFFFFFFF # Sign extended then treated as unsigned
                        registers[rd] = 1 if v1 < u_imm else 0
            
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

            elif op == 'jalr':
                rd = parse_register(parts[1])
                match = re.match(r'(-?\d+)\s*\(\s*(x\d+)\s*\)', parts[2])
                if match:
                    imm = int(match.group(1))
                    rs1 = parse_register(match.group(2))
                    # Stop if it finds exactly jalr x0, 0(x1)
                    if rd == 0 and rs1 == 1 and imm == 0:
                        break

            pc += 1

    return regfiles, memory

def main():
    # Set this to match your Verilog NUM_CORES parameter
    num_cores = NUM_CORES 
    
    current_dir = Path('.')
    asm_files = []
    
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
        asm_files = [Path(target_dir) / 'program.asm']
    else:
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