import os
import random
import subprocess
import shutil
import argparse 
from program_checker import analyze_multicore_assembly # <-- NEW IMPORT

# Configuration
INSTRUCTIONS_PER_TEST = 50
RANDOM_TEST_DIR = "test999"

# Register pools
# x1 is reserved as a safe memory base pointer (0)
# x0 is hardwired 0, x31 is Core ID
AVAILABLE_REGS = [f"x{i}" for i in range(2, 31)]
OPCODES = ['add', 'sub', 'addi', 'mul', 'lw', 'sw', 'amoadd.w', 'beq', 'and', 'andi', 'or', 'sll', 'slli', 'sra', 'srai', 'srl', 'srli', 'slt', 'slti', 'sltu', 'sltiu']

def generate_random_assembly(filepath):
    """Generates a highly-biased RISC-V assembly program designed to break hardware pipelines."""
    asm = []
    
    # 1. Initialization
    asm.append("# INITIALIZATION")
    asm.append("addi x1, x0, 0  # Reserved Base Memory Pointer (Address 0)")
    
    for i in range(2, 31):
        asm.append(f"addi x{i}, x0, {random.randint(-10, 10)}")
        
    asm.append("\n# BIASED RANDOM OPERATIONS")
    
    pending_labels = []
    label_counter = 0
    last_dest_reg = "x2" # Track the last written register for dependency forcing
    
    instructions_generated = 0
    
    while instructions_generated < INSTRUCTIONS_PER_TEST:
        # ---------------------------------------------------------
        # STRATEGY 1: INJECT "EVIL SEQUENCES" (20% chance)
        # ---------------------------------------------------------
        if random.random() < 0.20 and instructions_generated < INSTRUCTIONS_PER_TEST - 3:
            sequence_type = random.choice(['load_use', 'store_load', 'mul_trap', 'back_to_back_mem'])
            rd = random.choice(AVAILABLE_REGS)
            rs = random.choice(AVAILABLE_REGS)
            mem_offset = random.choice([0, 4, 8, 12])
            
            asm.append(f"\n# --- EVIL SEQUENCE: {sequence_type.upper()} ---")
            if sequence_type == 'load_use':
                asm.append(f"lw {rd}, {mem_offset}(x1)")
                asm.append(f"add {rs}, {rd}, {rd}") # Immediate RAW dependency
                instructions_generated += 2
                
            elif sequence_type == 'store_load':
                asm.append(f"sw {rs}, {mem_offset}(x1)")
                asm.append(f"lw {rd}, {mem_offset}(x1)") # BRAM bypass / read-after-write
                instructions_generated += 2
                
            elif sequence_type == 'mul_trap':
                rd2 = random.choice(AVAILABLE_REGS)
                asm.append(f"mul {rd}, {rs}, {rs}")
                asm.append(f"addi {rd2}, x0, 5")     # Independent instruction sneaks into pipeline
                asm.append(f"add {rs}, {rd}, {rd2}") # Dependent instruction traps the pipeline
                instructions_generated += 3
                
            elif sequence_type == 'back_to_back_mem':
                asm.append(f"lw {rd}, {mem_offset}(x1)")
                asm.append(f"lw {rs}, {random.choice([0,4,8,12])}(x1)") # The bug you just fixed!
                instructions_generated += 2
                
            last_dest_reg = rs
            continue

        # ---------------------------------------------------------
        # STRATEGY 2: STANDARD GENERATION WITH BIASED DEPENDENCIES
        # ---------------------------------------------------------
        op = random.choice(OPCODES)
        rd = random.choice(AVAILABLE_REGS)
        
        # 50% chance to force the source register to be the exact destination 
        # of the previous instruction, forcing the Forwarding Unit to activate.
        rs1 = last_dest_reg if random.random() < 0.5 else random.choice(AVAILABLE_REGS)
        rs2 = last_dest_reg if random.random() < 0.5 else random.choice(AVAILABLE_REGS)
        
        # Helper to generate evil immediate values
        def get_evil_imm():
            if random.random() < 0.3: # 30% chance for an edge-case number
                return random.choice([0, 1, -1, 2047, -2048])
            return random.randint(-50, 50)

        if op in ['add', 'sub', 'mul', 'and', 'or', 'sll', 'srl', 'sra', 'slt', 'sltu']:
            asm.append(f"{op} {rd}, {rs1}, {rs2}")
            last_dest_reg = rd
            
        elif op in ['addi', 'andi', 'slti', 'sltiu']:
            asm.append(f"{op} {rd}, {rs1}, {get_evil_imm()}")
            last_dest_reg = rd

        elif op in ['slli', 'srli', 'srai']:
            asm.append(f"{op} {rd}, {rs1}, {random.randint(0, 31)}")
            last_dest_reg = rd
            
        elif op in ['lw', 'sw', 'amoadd.w']:
            # MEMORY HOT-SPOTTING: Only use restricted addresses to guarantee BRAM contention.
            offset = random.choice([0, 4, 8, 12, 16])
            if op == 'amoadd.w':
                # amoadd.w doesn't take an immediate offset in syntax, so we use x1 
                # (which is hardwired to Base Address 0) to guarantee a collision hotspot.
                asm.append(f"{op} {rd}, {rs1}, (x1)")
                last_dest_reg = rd
            else:
                asm.append(f"{op} {rd}, {offset}(x1)")
                if op == 'lw':
                    last_dest_reg = rd
            
        elif op == 'beq':
            target = f"skip_{label_counter}"
            pending_labels.append(target)
            label_counter += 1
            asm.append(f"beq {rs1}, {rs2}, {target}")
            
        if pending_labels and random.random() < 0.3:
            asm.append(f"{pending_labels.pop(0)}:")

        instructions_generated += 1

    # Place any remaining unresolved labels at the end
    for lbl in pending_labels:
        asm.append(f"{lbl}:")
        
    asm.append("\n# KERNEL COMPLETE TRAP")
    asm.append("jalr x0, 0(x1)")
    
    with open(filepath, 'w') as f:
        f.write("\n".join(asm) + "\n")

def clean_random_test_files():
    """Deletes only the generated files in the random test directory."""
    files_to_remove = [
        "program.mem", 
        "data.mem", 
        "trace.csv"
    ]
    # Also clean up generated regfiles for all cores
    for f in os.listdir(RANDOM_TEST_DIR):
        if f in files_to_remove or f.startswith("regfile_c"):
            os.remove(os.path.join(RANDOM_TEST_DIR, f))

def main():
    # NEW: Parse command line arguments
    parser = argparse.ArgumentParser(description="Multi-Core RISC-V Random Fuzzer")
    parser.add_argument("-i", "--iterations", type=int, default=100, 
                        help="Number of random tests to generate and run")
    args = parser.parse_args()

    if not os.path.exists(RANDOM_TEST_DIR):
        os.makedirs(RANDOM_TEST_DIR)
        
    asm_filepath = os.path.join(RANDOM_TEST_DIR, "program.asm")
    
    print(f"Starting Multi-Core Random Test Fuzzer ({args.iterations} iterations)...")
    print("==================================================================")
    
    for i in range(1, args.iterations + 1):
        print(f"--> Iteration {i}/{args.iterations}: Generating test...")
        
        # 1. Generate and Validate new random ASM
        # We loop until the checker approves the generated code
        while True:
                generate_random_assembly(asm_filepath)
                
                with open(asm_filepath, 'r') as f:
                    asm_code = f.read()
                    
                # Use your checker to silently validate the code!
                if analyze_multicore_assembly(asm_code, num_cores=4):
                    break # It's safe! Break the loop and proceed to simulation.
                else:
                    print("    [!] Fuzzer generated a divergent sequence. Regenerating...")
        
        # 2. Build ONLY the random test folder to save massive amounts of time
        subprocess.run(["python3", "assembler.py", RANDOM_TEST_DIR], capture_output=True)
        subprocess.run(["python3", "expected_generator.py", RANDOM_TEST_DIR], capture_output=True)
        
        # 3. Run the Verilog simulation only
        subprocess.run(["make", "compile"], capture_output=True)
        result = subprocess.run(["vvp", "./main", f"+TEST_IDX=999"], capture_output=True, text=True)
        
        # 4. Check results
        if "[FAIL]" in result.stdout or "[Error]" in result.stdout or "[PASS]" not in result.stdout:
            print(f"\n[!!!] ITERATION {i} FAILED! [!!!]")
            print("==================================================================")
            # Print the last 30 lines of the simulation output to show the exact mismatch
            print("\n".join(result.stdout.splitlines()[-30:]))
            print("==================================================================")
            print(f"Simulation stopped. The failing test has been preserved in '{RANDOM_TEST_DIR}/'")
            print("Check 'program.asm' and the generated memories to debug.")
            break
        else:
            print(f"    [PASS] Iteration {i} successful.")
            # 5. Cleanup to prevent clogging
            clean_random_test_files()
            
    else:
        print("\n==================================================================")
        print(f"SUCCESS! All {args.iterations} random tests passed flawlessly.")
        print("==================================================================")

if __name__ == "__main__":
    main()