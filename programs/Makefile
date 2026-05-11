# --- RISC-V Cross-Compiler Variables ---
CC = riscv64-unknown-elf-gcc
OBJDUMP = riscv64-unknown-elf-objdump
CFLAGS = -O0 -march=rv32im -mabi=ilp32 -ffreestanding -nostdlib -Ttext=0x00000000

# --- Native (x86 Linux) Compiler Variables ---
NATIVE_CC = gcc
NATIVE_CFLAGS = -O2

PROG ?= nbody

DIR = $(PROG)

SRC = $(DIR)/$(PROG).c
NATIVE_SRC = $(SRC)

# RISC-V Outputs
ELF = $(DIR)/$(PROG).elf
ASM = $(DIR)/$(PROG)_dump_real.asm
MEM = $(DIR)/$(PROG)_instructions.mem

# Native x86 Output
NATIVE_EXE = $(DIR)/$(PROG)_x86

# Default target builds both architectures
all: riscv x86

riscv: $(MEM)
x86: $(NATIVE_EXE)

# ==========================================
# NATIVE x86 BUILD TARGET
# ==========================================
$(NATIVE_EXE): $(NATIVE_SRC)
	@echo "Compiling $(PROG) for x86 Native Linux..."
	@$(NATIVE_CC) $(NATIVE_CFLAGS) -o $@ $<
	@echo "Success! Run it with: ./$@"

# ==========================================
# RISC-V BARE-METAL BUILD TARGETS
# ==========================================

# Create the Memory File (.mem) from the Assembly Dump
$(MEM): $(ASM)
	@echo "Filtering and creating Memory File (replacing jalr)..."
	@awk '/^[[:space:]]*[0-9a-fA-F]+:/ { \
		hex_code = $$2; \
		instruction = $$3; \
		if (length(hex_code) == 8) { \
			if (instruction == "jalr") { \
				print "00000063"; \
			} else { \
				print hex_code; \
			} \
		} \
	}' $< > $@
	@echo "Success! RISC-V Memory File is ready: $@"

# Create the Assembly Dump (.asm) from the ELF executable
$(ASM): $(ELF)
	@echo "Extracting real assembly instructions..."
	@$(OBJDUMP) -d -M no-aliases,numeric $< > $@
	@echo "---------------------------------------------------"
	@echo "Instruction Set used in $(PROG) (RISC-V):"
	@awk '/^[[:space:]]*[0-9a-fA-F]+:/ {print $$3}' $@ | sort -u | tr '\n' ' '
	@echo ""
	@echo "---------------------------------------------------"

# Compile the C source code into a RISC-V ELF executable
$(ELF): $(SRC)
	@echo "Compiling $(PROG) for RISC-V..."
	@$(CC) $(CFLAGS) -o $@ $<

# Clean up generated files for both architectures
clean:
	@echo "Cleaning up files for $(PROG)..."
	@rm -f $(ELF) $(ASM) $(MEM) $(NATIVE_EXE)

# Declare non-file targets
.PHONY: all riscv x86 clean
