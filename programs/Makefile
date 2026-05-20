# --- RISC-V Cross-Compiler Variables ---
CC = riscv64-unknown-elf-gcc
OBJDUMP = riscv64-unknown-elf-objdump
CFLAGS = -O0 -march=rv32im -mabi=ilp32 \
          -ffreestanding -nostdlib \
          -fomit-frame-pointer \
          -Ttext=0x00000000

# --- Native (x86 Linux) Compiler Variables ---
NATIVE_CC = gcc
NATIVE_CFLAGS = -O0

PROG ?= nbody

DIR = $(PROG)

SRC = $(DIR)/$(PROG).c
NATIVE_SRC = $(SRC)

# ==========================================
# RISC-V Outputs
# ==========================================
ELF      = $(DIR)/$(PROG).elf

# Full dump:
# address + hex + instruction
DUMP_ASM = $(DIR)/$(PROG)_dump_real.asm

# Clean assembly only
PROG_ASM = $(DIR)/$(PROG)_program.asm

# Raw hex instructions
MEM      = $(DIR)/$(PROG)_instructions.mem

# ==========================================
# Native x86 Output
# ==========================================
NATIVE_EXE = $(DIR)/$(PROG)_x86

# ==========================================
# Default target
# ==========================================
all: riscv x86

riscv: $(MEM) $(PROG_ASM)
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

# ------------------------------------------
# Full assembly dump
# ------------------------------------------
$(DUMP_ASM): $(ELF)
	@echo "Generating full assembly dump..."
	@$(OBJDUMP) -d -M no-aliases,numeric $< > $@

	@echo "---------------------------------------------------"
	@echo "Instruction Set used in $(PROG) (RISC-V):"
	@awk '/^[[:space:]]*[0-9a-fA-F]+:/ {print $$3}' $@ \
		| sort -u | tr '\n' ' '
	@echo ""
	@echo "---------------------------------------------------"

# ------------------------------------------
# Clean assembly only
# ------------------------------------------
$(PROG_ASM): $(DUMP_ASM)
	@echo "Generating clean assembly listing..."

	@awk '/^[[:space:]]*[0-9a-fA-F]+:/ { \
		printf("%s", $$3); \
		for(i=4;i<=NF;i++) \
			printf(" %s", $$i); \
		printf("\n"); \
	}' $< > $@

	@echo "Success! Program assembly ready: $@"

# ------------------------------------------
# Create memory initialization file
# ------------------------------------------
$(MEM): $(DUMP_ASM)
	@echo "Filtering and creating Memory File..."

	@awk '/^[[:space:]]*[0-9a-fA-F]+:/ { \
		hex_code = $$2; \
		if (length(hex_code) == 8) { \
# 			skip = 0; \
			n = split($$0, tokens, /[ \t,()]+/); \
# 			for (i = 1; i <= n; i++) { \
# 				if (tokens[i] == "x2" || tokens[i] == "sp") { \
# 					skip = 1; \
# 					break; \
# 				} \
# 			} \
# 			if (!skip) \
				print hex_code; \
		} \
	}' $< > $@

	@echo "Success! Memory file ready: $@"

# ==========================================
# Compile C -> ELF
# ==========================================
$(ELF): $(SRC)
	@echo "Compiling $(PROG) for RISC-V..."
	@$(CC) $(CFLAGS) -o $@ $<

# ==========================================
# Clean
# ==========================================
clean:
	@echo "Cleaning up files for $(PROG)..."

	@rm -f \
		$(ELF) \
		$(DUMP_ASM) \
		$(PROG_ASM) \
		$(MEM) \
		$(NATIVE_EXE)

# ==========================================
# Phony targets
# ==========================================
.PHONY: all riscv x86 clean