# --- RISC-V Cross-Compiler Variables ---
CROSS_PREFIX ?= $(shell if command -v riscv64-unknown-elf-gcc >/dev/null 2>&1; then printf riscv64-unknown-elf; elif command -v riscv-none-elf-gcc >/dev/null 2>&1; then printf riscv-none-elf; else printf riscv64-unknown-elf; fi)
CC = $(CROSS_PREFIX)-gcc
OBJDUMP = $(CROSS_PREFIX)-objdump
LINKER_SCRIPT = gpgpu.ld
CFLAGS = -O2 -march=rv32im -mabi=ilp32 \
          -ffreestanding -fno-builtin \
          -fomit-frame-pointer -ffixed-x31 \
          -ffunction-sections -fdata-sections \
          -msmall-data-limit=0 -mno-relax
LDFLAGS = -nostdlib -nostartfiles \
          -Wl,-T,$(LINKER_SCRIPT) \
          -Wl,-Map,$(MAP) \
          -Wl,--build-id=none

# --- Native (x86 Linux) Compiler Variables ---
NATIVE_CC = gcc
NATIVE_CFLAGS = -O2

PROG ?= nbody

DIR = $(PROG)

SRC = $(DIR)/$(PROG).c
NATIVE_SRC = $(SRC)

# ==========================================
# RISC-V Outputs
# ==========================================
ELF      = $(DIR)/$(PROG).elf
MAP      = $(DIR)/$(PROG).map

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

riscv: $(PROG_ASM)
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
			n = split($$0, tokens, /[ \t,()]+/); \
			print hex_code; \
		} \
	}' $< > $@

	@echo "Success! Memory file ready: $@"

# ==========================================
# Compile C -> ELF
# ==========================================
$(ELF): $(SRC) $(LINKER_SCRIPT)
	@echo "Compiling $(PROG) for RISC-V..."
	@$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

# ==========================================
# Clean
# ==========================================
clean:
	@echo "Cleaning up files for $(PROG)..."

	@rm -f \
		$(ELF) \
		$(MAP) \
		$(DUMP_ASM) \
		$(PROG_ASM) \
		$(MEM) \
		$(NATIVE_EXE)

# ==========================================
# Phony targets
# ==========================================
.PHONY: all riscv x86 clean