import os
import random
import subprocess
import shutil
import argparse # NEW: For command line arguments
import sys
from pathlib import Path
from typing import TextIO

# Configuration
INSTRUCTIONS_PER_TEST = 50
RANDOM_TEST_DIR = "cases/test999"
RANDOM_TEST_INDEX = 999

# Register pools
# x1 is reserved as a safe memory base pointer (0)
# x0 is hardwired 0, x31 is Core ID
AVAILABLE_REGS = [f"x{i}" for i in range(2, 31)]
OPCODES = ['add', 'sub', 'addi', 'mul', 'lw', 'sw', 'beq', 'and', 'andi', 'or', 'sll', 'slli', 'sra', 'srai', 'srl', 'srli', 'slt', 'slti', 'sltu', 'sltiu']

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
            
        elif op in ['lw', 'sw']:
            # MEMORY HOT-SPOTTING: Only use addresses 0, 4, 8, 12, 16.
            # This guarantees crossbar collisions and BRAM read/write contention.
            offset = random.choice([0, 4, 8, 12, 16])
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

def clean_random_test_files(random_test_dir=RANDOM_TEST_DIR):
    """Deletes only the generated files in the random test directory."""
    files_to_remove = [
        "program.mem", 
        "data.mem", 
        "trace.csv",
        ".gpgpu-random-test", # Cleanup marker created by earlier runner versions
    ]
    # Also clean up generated regfiles for all cores
    for f in os.listdir(random_test_dir):
        if f in files_to_remove or f.startswith("regfile_c"):
            os.remove(os.path.join(random_test_dir, f))

def print_and_log(message, log: TextIO):
    """Print one status line and append it to the random-test log."""
    print(message, flush=True)
    log.write(f"{message}\n")
    log.flush()

def run_generator(command, cwd, log):
    """Run one generator and report its captured output if it fails."""
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode == 0:
        return True

    print_and_log(f"[ERROR] Command failed with status {result.returncode}: {' '.join(command)}", log)
    for line in (result.stdout + result.stderr).splitlines():
        print_and_log(line, log)
    return False

def run_simulation(command, cwd, log):
    """Stream simulator output to both the terminal and the log."""
    result_lines = []
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if process.stdout is None:
        raise RuntimeError("Random simulator output pipe was not created")

    for line in process.stdout:
        print(line, end="", flush=True)
        log.write(line)
        log.flush()
        result_lines.append(line)

    return process.wait(), "".join(result_lines)

def main():
    # NEW: Parse command line arguments
    parser = argparse.ArgumentParser(description="Multi-Core RISC-V Random Fuzzer")
    parser.add_argument("-i", "--iterations", type=int, default=100, 
                        help="Number of random tests to generate and run")
    parser.add_argument("--seed", type=int,
                        help="Base seed used to reproduce a random-test run")
    parser.add_argument("--python", default=sys.executable,
                        help="Python command used for the test generators")
    parser.add_argument("--vvp", default="vvp",
                        help="Configured vvp command")
    parser.add_argument("--simulator", type=Path, default=Path("./main"),
                        help="Precompiled SMX simulator executable")
    parser.add_argument("--test-root", type=Path, default=Path.cwd(),
                        help="RTL test directory containing cases/")
    parser.add_argument("--log", type=Path, default=Path("random.log"),
                        help="Random simulation log path")
    args = parser.parse_args()

    if args.iterations < 1:
        parser.error("--iterations must be at least 1")

    random_test_dir = args.test_root.resolve() / RANDOM_TEST_DIR
    if not os.path.exists(random_test_dir):
        os.makedirs(random_test_dir)
        
    asm_filepath = os.path.join(random_test_dir, "program.asm")
    tools_dir = Path(__file__).resolve().parent
    base_seed = args.seed
    if base_seed is None:
        base_seed = random.SystemRandom().getrandbits(64)

    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("w", encoding="utf-8") as log:
        print_and_log(f"Starting Multi-Core Random Test Fuzzer ({args.iterations} iterations)...", log)
        print_and_log(f"Base seed: {base_seed}", log)
        print_and_log("==================================================================", log)
        
        for i in range(1, args.iterations + 1):
            iteration_seed = base_seed + i - 1
            print_and_log(f"--> Iteration {i}/{args.iterations}: Generating test with seed {iteration_seed}...", log)
            
            # 1. Generate new random ASM
            random.seed(iteration_seed)
            generate_random_assembly(asm_filepath)
            
            # 2. Build ONLY the random test folder to save massive amounts of time
            if not run_generator([args.python, str(tools_dir / "assembler.py"), str(random_test_dir)], args.test_root, log):
                print_and_log(f"Simulation stopped. The failing test has been preserved in '{random_test_dir}/'", log)
                return 1
            if not run_generator([args.python, str(tools_dir / "expected_generator.py"), str(random_test_dir)], args.test_root, log):
                print_and_log(f"Simulation stopped. The failing test has been preserved in '{random_test_dir}/'", log)
                return 1
            
            # 3. Run the Verilog simulation only
            # The tests:rtl:smx:build dependency compiles the simulator once.
            returncode, simulation_output = run_simulation(
                [
                    args.vvp,
                    "-i",
                    str(args.simulator.resolve()),
                    f"+TEST_IDX={RANDOM_TEST_INDEX}",
                    f"+TEST_END={RANDOM_TEST_INDEX}",
                ],
                args.test_root,
                log,
            )
            
            # 4. Check results
            if returncode != 0 or "[WARNING]" in simulation_output or "[ERROR]" in simulation_output or "[FAIL]" in simulation_output or "[SUCCESS]" not in simulation_output:
                print_and_log(f"\n[!!!] ITERATION {i} FAILED! [!!!]", log)
                print_and_log("==================================================================", log)
                # Print the last 30 lines of the simulation output to show the exact mismatch
                for line in simulation_output.splitlines()[-30:]:
                    print_and_log(line, log)
                print_and_log("==================================================================", log)
                print_and_log(f"Simulation stopped. The failing test has been preserved in '{random_test_dir}/'", log)
                print_and_log("Check 'program.asm' and the generated memories to debug.", log)
                return 1
            else:
                print_and_log(f"    [PASS] Iteration {i} successful.", log)
                # 5. Cleanup to prevent clogging
                clean_random_test_files(random_test_dir)
                
        print_and_log("\n==================================================================", log)
        print_and_log(f"SUCCESS! All {args.iterations} random tests passed flawlessly.", log)
        print_and_log("==================================================================", log)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
