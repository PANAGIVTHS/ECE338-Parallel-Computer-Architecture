import os
import re
import argparse
import sys
from pathlib import Path

# Memory configurations
MEM_DEPTH = 2048
REG_DEPTH = 32
NUM_CORES = 32
STACK_P_INIT = 0

def load_dmem_seed(seed_path):
    """Load an optional $readmemh-style DMEM seed file.

    Supports plain one-word-per-line files and sparse address directives such as
    '@10' followed by words.  This mirrors the subset of $readmemh syntax used by
    the Verilog testbench for per-test initial data memory.
    """
    memory = [0] * MEM_DEPTH
    if not seed_path.exists():
        return memory

    addr = 0
    with open(seed_path, 'r', encoding='utf-8') as f:
        for line_no, line in enumerate(f, start=1):
            code = line.split('#')[0].split('//')[0].strip()
            if not code:
                continue

            for token in code.split():
                if token.startswith('@'):
                    addr = int(token[1:], 16)
                    if addr < 0 or addr >= MEM_DEPTH:
                        raise ValueError(f"{seed_path}:{line_no}: seed address @{addr:x} outside DMEM depth {MEM_DEPTH}")
                    continue

                if addr >= MEM_DEPTH:
                    raise ValueError(f"{seed_path}:{line_no}: too many seed words for DMEM depth {MEM_DEPTH}")
                memory[addr] = int(token, 16) & 0xFFFFFFFF
                addr += 1

    return memory

def parse_register(reg_str):
    """Extracts the integer index from a register string like 'x1', 'x31'"""
    return int(reg_str.replace('x', '').replace(',', ''), 0)

def format_hex(val):
    """Formats an integer into an 8-character 32-bit hex string"""
    # Force the value into a 32-bit unsigned integer range
    val_32bit = val & 0xFFFFFFFF
    return f"{val_32bit:08x}"

def parse_objdump_addr(addr_str):
    """Parse objdump-style bare hexadecimal addresses such as '1c' or '438'."""
    token = addr_str.strip().rstrip(',')
    sign = -1 if token.startswith('-') else 1
    if token[0] in '+-':
        token = token[1:]
    base = 16 if not token.lower().startswith('0x') else 0
    return sign * int(token, base)

def has_objdump_symbol(parts, target_index):
    """Return true for objdump operands like: jal x1,1c <nbody_kernel>."""
    return len(parts) > target_index + 1 and parts[target_index + 1].startswith('<')

def resolve_control_target(target, pc, labels, absolute_address=False):
    """Return an instruction-index target for branch/jal operands.

    Existing handwritten tests use labels or PC-relative byte immediates. The
    generated nbody assembly copied from objdump uses absolute byte addresses
    with symbolic annotations, e.g. '438 <nbody_kernel+0x41c>'. Treat those
    annotated numeric operands as absolute PCs while preserving old relative
    immediate behavior for unannotated numeric operands.
    """
    if target in labels:
        return labels[target]
    if absolute_address:
        return parse_objdump_addr(target) // 4
    imm = int(target, 0)
    return pc + (imm // 4)

def generate_expected_memories(asm_text, num_cores=2, initial_memory=None):
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

    # PASS 2: Simulate execution in LOCKSTEP (Cycle-by-Cycle)
    # Initialize state for all cores
    core_states = []
    for core_id in range(num_cores):
        regfiles[core_id][31] = core_id  # Hardwire x31 to CORE_ID
        regfiles[core_id][2] = STACK_P_INIT
        core_states.append({
            'pc': 0,
            'halted': False
        })

    cycles = 0
    max_cycles = 10000 # Safeguard against complex infinite loops
    
    # Lockstep Engine: Outer loop is Time (cycles)
    while not all(state['halted'] for state in core_states) and cycles < max_cycles:
        cycles += 1
        
        # Inner loop is Cores (Execute exactly 1 instruction per active core)
        for core_id in range(num_cores):
            state = core_states[core_id]
            registers = regfiles[core_id]
            
            if state['halted']:
                continue
                
            pc = state['pc']
            
            # Halt if PC falls off the end of the program
            if pc >= len(instructions):
                state['halted'] = True
                continue

            inst = instructions[pc]
            parts = inst.replace(',', ' ').split()
            op = parts[0].lower()
            next_pc = pc + 1  # Default next instruction pointer

            if op == 'nop':
                pass
                
            elif op in ['add', 'sub', 'mul', 'and', 'or', 'xor', 'sll', 'srl', 'sra', 'slt', 'sltu']:
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
                    elif op == 'xor':
                        registers[rd] = v1 ^ v2
                    elif op == 'sll':
                        registers[rd] = (v1 << (v2 & 0x1F)) & 0xFFFFFFFF
                    elif op == 'srl':
                        registers[rd] = (v1 >> (v2 & 0x1F)) & 0xFFFFFFFF
                    elif op == 'sra':
                        sv1 = v1 if v1 < 0x80000000 else v1 - 0x100000000
                        registers[rd] = (sv1 >> (v2 & 0x1F)) & 0xFFFFFFFF
                    elif op == 'slt':
                        sv1 = v1 if v1 < 0x80000000 else v1 - 0x100000000
                        sv2 = v2 if v2 < 0x80000000 else v2 - 0x100000000
                        registers[rd] = 1 if sv1 < sv2 else 0
                    elif op == 'sltu':
                        registers[rd] = 1 if v1 < v2 else 0
                        
            elif op in ['addi', 'andi', 'ori', 'xori', 'slli', 'srli', 'srai', 'slti', 'sltiu']:
                rd = parse_register(parts[1])
                rs1 = parse_register(parts[2])
                imm = int(parts[3], 0)
                if rd != 0 and rd != 31:
                    v1 = registers[rs1]
                    
                    if op == 'addi':
                        registers[rd] = (v1 + imm) & 0xFFFFFFFF
                    elif op == 'andi':
                        registers[rd] = (v1 & imm) & 0xFFFFFFFF
                    elif op == 'ori':
                        registers[rd] = (v1 | imm) & 0xFFFFFFFF
                    elif op == 'xori':
                        registers[rd] = (v1 ^ imm) & 0xFFFFFFFF
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
                        u_imm = imm & 0xFFFFFFFF 
                        registers[rd] = 1 if v1 < u_imm else 0
            
            elif op == 'lw' or op == 'sw':
                reg_a = parse_register(parts[1])
                match = re.match(r'(-?\d+)\s*\(\s*(x\d+)\s*\)', parts[2])
                if not match:
                    raise ValueError(f"Failed to parse memory offset in: {inst}")
                
                imm = int(match.group(1), 0)
                base_reg = parse_register(match.group(2))
                
                # Modulo Math: Accurately replicates BRAM index wrapping
                byte_addr = registers[base_reg] + imm
                word_idx = ((byte_addr & 0xFFFFFFFF) // 4) % MEM_DEPTH
                
                if op == 'lw':
                    if reg_a != 0 and reg_a != 31:
                        registers[reg_a] = memory[word_idx]
                elif op == 'sw':
                    memory[word_idx] = registers[reg_a]
                        
            elif op in ['beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu']:
                rs1 = parse_register(parts[1])
                rs2 = parse_register(parts[2])
                target = parts[3]
                v1 = registers[rs1]
                v2 = registers[rs2]
                sv1 = v1 if v1 < 0x80000000 else v1 - 0x100000000
                sv2 = v2 if v2 < 0x80000000 else v2 - 0x100000000
                take_branch = (
                    (op == 'beq' and v1 == v2) or
                    (op == 'bne' and v1 != v2) or
                    (op == 'blt' and sv1 < sv2) or
                    (op == 'bge' and sv1 >= sv2) or
                    (op == 'bltu' and v1 < v2) or
                    (op == 'bgeu' and v1 >= v2)
                )
                if take_branch:
                    target_pc = resolve_control_target(target, pc, labels, has_objdump_symbol(parts, 3))
                        
                    # Trap logic: Halt if jumping to the exact same instruction
                    if target_pc == pc:
                        state['halted'] = True
                    else:
                        next_pc = target_pc

            elif op == 'jal':
                rd = parse_register(parts[1])
                target = parts[2]
                if rd != 0 and rd != 31:
                    registers[rd] = ((pc + 1) * 4) & 0xFFFFFFFF
                if target in labels:
                    next_pc = labels[target]
                else:
                    next_pc = resolve_control_target(target, pc, labels, has_objdump_symbol(parts, 2))

            elif op == 'lui':
                rd = parse_register(parts[1])
                imm = int(parts[2], 0)

                if rd != 0 and rd != 31:
                    registers[rd] = (imm << 12) & 0xFFFFFFFF

            elif op == 'jalr':
                rd = parse_register(parts[1])
                if '(' in parts[2]:
                    match = re.match(r'(-?\d+)\s*\(\s*(x\d+)\s*\)', parts[2])
                    if not match:
                        raise ValueError(f"Failed to parse JALR operand in: {inst}")
                    imm = int(match.group(1), 0)
                    rs1 = parse_register(match.group(2))
                else:
                    rs1 = parse_register(parts[2])
                    imm = int(parts[3], 0)

                target_byte_addr = (registers[rs1] + imm) & 0xFFFFFFFE

                if rd != 0 and rd != 31:
                    registers[rd] = ((pc + 1) * 4) & 0xFFFFFFFF

                # convention: jalr x0, 0(x1) is reserved as the stop signal.
                if rd == 0 and rs1 == 1 and imm == 0:
                    state['halted'] = True
                else:
                    next_pc = (target_byte_addr // 4) % MEM_DEPTH
                        
            # Update PC
            state['pc'] = next_pc

        # END OF CYCLE: Hardware Grounding
        # Re-enforce x0 = 0 and x31 = CORE_ID physically at the end of every tick
        for core_id in range(num_cores):
            regfiles[core_id][0] = 0
            regfiles[core_id][31] = core_id

    if not all(state['halted'] for state in core_states):
        active = [(core_id, state['pc']) for core_id, state in enumerate(core_states) if not state['halted']]
        active_pcs = sorted({pc for _, pc in active})
        raise RuntimeError(
            f"Expected generator reached max_cycles={max_cycles} before all cores halted; "
            f"active core/PC pairs={active}; active PCs={active_pcs}. "
            f"Refusing to write partial expected memories."
        )

    return regfiles, memory

def main():
    num_cores = NUM_CORES 
    current_dir = Path('.')
    asm_files = []
    
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
        asm_files = [Path(target_dir) / 'program.asm']
    else:
        for path in current_dir.glob('tests/test*/program.asm'):
            if re.fullmatch(r'test\d+', path.parent.name):
                asm_files.append(path)
        asm_files.sort(key=lambda p: int(p.parent.name.replace('test', ''), 0))

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

        seed_path = test_dir / "dmem_seed.mem"
        initial_memory = load_dmem_seed(seed_path)
        if seed_path.exists():
            print(f"  -> Loaded initial DMEM seed from {seed_path.name}")

        regfiles, memory = generate_expected_memories(asm_code, num_cores, initial_memory=initial_memory)
            
        for core_id in range(num_cores):
            reg_filename = test_dir / f"regfile_c{core_id}.mem"
            with open(reg_filename, 'w') as f:
                for val in regfiles[core_id]:
                    f.write(format_hex(val) + "\n")
            print(f"  -> Generated {reg_filename.name}")

        data_filename = test_dir / "data.mem"
        with open(data_filename, 'w') as f:
            for val in memory:
                f.write(format_hex(val) + "\n")
        print(f"  -> Generated {data_filename.name}\n")

    print("Expected memory generation complete!")

if __name__ == "__main__":
    main()