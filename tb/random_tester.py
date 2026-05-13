import os
import random
import subprocess
import shutil
import argparse # NEW: For command line arguments

# Configuration
INSTRUCTIONS_PER_TEST = 50
RANDOM_TEST_DIR = "test999"

# Register pools
# x1 is reserved as a safe memory base pointer (0)
# x0 is hardwired 0, x31 is Core ID
AVAILABLE_REGS = [f"x{i}" for i in range(2, 31)]
OPCODES = ['add', 'sub', 'addi', 'mul', 'lw', 'sw', 'beq', 'and', 'andi', 'or', 'sll', 'slli', 'sra', 'srai', 'srl', 'srli', 'slt', 'slti', 'sltu', 'sltiu']

def generate_random_assembly(filepath):
    """Generates a randomized but safe RISC-V assembly program."""
    asm = []
    
    # 1. Initialization
    asm.append("# INITIALIZATION")
    asm.append("addi x1, x0, 0  # Reserved Base Memory Pointer (Address 0)")
    
    # Initialize a few random registers to prevent propagating too many zeros
    for i in range(2, 6):
        asm.append(f"addi x{i}, x0, {random.randint(-50, 50)}")
        
    asm.append("\n# RANDOM OPERATIONS")
    
    pending_labels = []
    label_counter = 0
    
    for _ in range(INSTRUCTIONS_PER_TEST):
        op = random.choice(OPCODES)
        rd = random.choice(AVAILABLE_REGS)
        rs1 = random.choice(AVAILABLE_REGS)
        rs2 = random.choice(AVAILABLE_REGS)
        
        if op in ['add', 'sub', 'mul', 'and', 'or', 'sll', 'srl', 'sra', 'slt', 'sltu']:
            asm.append(f"{op} {rd}, {rs1}, {rs2}")
            
        elif op in ['addi', 'andi', 'slti', 'sltiu']:
            imm = random.randint(-100, 100)
            asm.append(f"{op} {rd}, {rs1}, {imm}")

        elif op in ['slli', 'srli', 'srai']:
            imm = random.randint(0, 31) # Shifts are bounded between 0 and 31
            asm.append(f"{op} {rd}, {rs1}, {imm}")
            
        elif op in ['lw', 'sw']:
            # Safe memory access: Word-aligned offset between 0 and 4000 (Max is 4092)
            # Uses x1 as the base to guarantee it stays in bounds
            offset = random.randint(0, 1000) * 4
            asm.append(f"{op} {rd}, {offset}(x1)")
            
        elif op == 'beq':
            # Create a label to jump FORWARD to (prevents infinite loops)
            target = f"skip_{label_counter}"
            pending_labels.append(target)
            label_counter += 1
            asm.append(f"beq {rs1}, {rs2}, {target}")
            
        # Randomly place one of the pending labels to resolve a branch
        if pending_labels and random.random() < 0.3:
            asm.append(f"{pending_labels.pop(0)}:")

    # Place any remaining unresolved labels at the end of the random block
    for lbl in pending_labels:
        asm.append(f"{lbl}:")
        
    # 3. Safe End Trap
    asm.append("\n# INFINITE LOOP TRAP")
    asm.append("end_trap:")
    asm.append("beq x0, x0, end_trap")
    
    # Write to file
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
        
        # 1. Generate new random ASM
        generate_random_assembly(asm_filepath)
        
        # 2. Build ONLY the random test folder to save massive amounts of time
        subprocess.run(["python3", "assembler.py", RANDOM_TEST_DIR], capture_output=True)
        subprocess.run(["python3", "expected_generator.py", RANDOM_TEST_DIR], capture_output=True)
        
        # 3. Run the Verilog simulation only
        result = subprocess.run(["make", "simulate"], capture_output=True, text=True)
        
        # 4. Check results
        if "[FAIL]" in result.stdout or "Error" in result.stdout or result.returncode != 0:
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