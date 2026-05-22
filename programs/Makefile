# ==========================================
# RISC-V Toolchain
# ==========================================

CC      = riscv64-unknown-elf-gcc
OBJDUMP = riscv64-unknown-elf-objdump

# ==========================================
# Runtime
# ==========================================

RUNTIME_DIR = runtime

STARTUP = $(RUNTIME_DIR)/startup.S
LINKER  = $(RUNTIME_DIR)/linker.ld

# ==========================================
# Compiler Flags
# ==========================================

CFLAGS = -O2 \
          -march=rv32im \
          -mabi=ilp32 \
          -ffreestanding \
          -nostdlib

# ==========================================
# Native Compiler
# ==========================================

NATIVE_CC = gcc
NATIVE_CFLAGS = -O2

# ==========================================
# Program Selection
# ==========================================

PROG ?= nbody

DIR = $(PROG)

SRC = $(DIR)/$(PROG).c
NATIVE_SRC = $(SRC)

# ==========================================
# Outputs
# ==========================================

ELF      = $(DIR)/$(PROG).elf

DUMP_ASM = $(DIR)/$(PROG)_dump_real.asm

PROG_ASM = $(DIR)/$(PROG)_program.asm

MEM      = $(DIR)/$(PROG)_instructions.mem

NATIVE_EXE = $(DIR)/$(PROG)_x86

# ==========================================
# Default Targets
# ==========================================

all: riscv x86

riscv: $(MEM) $(PROG_ASM)

x86: $(NATIVE_EXE)

# ==========================================
# Native Build
# ==========================================

$(NATIVE_EXE): $(NATIVE_SRC)
	@echo "Compiling $(PROG) for x86..."
	@$(NATIVE_CC) $(NATIVE_CFLAGS) \
		-o $@ $<

# ==========================================
# Full Assembly Dump
# ==========================================

$(DUMP_ASM): $(ELF)
	@echo "Generating full assembly dump..."

	@$(OBJDUMP) -d -M no-aliases,numeric \
		$< > $@

	@echo "---------------------------------------------------"
	@echo "Instruction Set used in $(PROG):"

	@awk '/^[[:space:]]*[0-9a-fA-F]+:/ {print $$3}' $@ \
		| sort -u | tr '\n' ' '

	@echo ""
	@echo "---------------------------------------------------"

# ==========================================
# Clean Assembly Listing
# ==========================================

$(PROG_ASM): $(DUMP_ASM)
	@echo "Generating clean assembly listing..."

	@awk '/^[[:space:]]*[0-9a-fA-F]+:/ { \
		printf("%s", $$3); \
		for(i=4;i<=NF;i++) \
			printf(" %s", $$i); \
		printf("\n"); \
	}' $< > $@

# ==========================================
# Memory Initialization File
# ==========================================

$(MEM): $(DUMP_ASM)
	@echo "Generating memory initialization file..."

	@awk '/^[[:space:]]*[0-9a-fA-F]+:/ { \
		hex_code = $$2; \
		if(length(hex_code) == 8) \
			print hex_code; \
	}' $< > $@

# ==========================================
# Compile + Link
# ==========================================

$(ELF): $(SRC) $(STARTUP) $(LINKER)
	@echo "Compiling $(PROG) for RISC-V..."

	@$(CC) $(CFLAGS) \
		-T $(LINKER) \
		-o $@ \
		$(STARTUP) \
		$<

# ==========================================
# Clean
# ==========================================

clean:
	@echo "Cleaning..."

	@rm -f \
		$(ELF) \
		$(DUMP_ASM) \
		$(PROG_ASM) \
		$(MEM) \
		$(NATIVE_EXE)

# ==========================================
# Phony Targets
# ==========================================

.PHONY: all riscv x86 clean