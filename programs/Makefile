# --- RISC-V Cross-Compiler Variables ---
CROSS_PREFIX ?= $(shell if command -v riscv64-unknown-elf-gcc >/dev/null 2>&1; then printf riscv64-unknown-elf; elif command -v riscv-none-elf-gcc >/dev/null 2>&1; then printf riscv-none-elf; else printf riscv64-unknown-elf; fi)
CC = $(CROSS_PREFIX)-gcc
OBJDUMP = $(CROSS_PREFIX)-objdump
LINKER_SCRIPT = gpgpu.ld
RECONV_SCRIPT = insert_reconvergence.py
# Set BRANCH_RECONVERGENCE=1 to use the transformed instruction stream with
# custom `ssy` reconvergence markers. Default is off until RTL decodes `ssy`.
BRANCH_RECONVERGENCE ?= 0
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

# Clean assembly only. With BRANCH_RECONVERGENCE=1 this file is rewritten by
# insert_reconvergence.py and contains custom `ssy` markers before branches.
PROG_ASM = $(DIR)/$(PROG)_program.asm

# Optional review artifacts generated without replacing the normal program asm/mem.
RECONV_ASM    = $(DIR)/$(PROG)_program_reconv.asm
RECONV_MEM    = $(DIR)/$(PROG)_instructions_reconv.mem
RECONV_REPORT = $(DIR)/$(PROG)_reconvergence.json
RECONV_STAMP  = $(DIR)/.reconvergence.stamp

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
reconvergence: $(RECONV_ASM) $(RECONV_MEM)

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
ifeq ($(BRANCH_RECONVERGENCE),1)
$(PROG_ASM) $(MEM): $(DUMP_ASM) $(RECONV_SCRIPT)
	@echo "Generating assembly and memory with SSY reconvergence markers..."
	@python3 $(RECONV_SCRIPT) \
		--input $(DUMP_ASM) \
		--asm-out $(PROG_ASM) \
		--mem-out $(MEM) \
		--report-out $(RECONV_REPORT)
	@echo "Success! Reconvergence-enabled assembly ready: $(PROG_ASM)"
	@echo "Success! Reconvergence-enabled memory ready: $(MEM)"
else
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
endif

# ------------------------------------------
# Optional reconvergence review artifacts without replacing normal outputs
# ------------------------------------------
$(RECONV_STAMP): $(DUMP_ASM) $(RECONV_SCRIPT)
	@echo "Generating optional SSY reconvergence review artifacts..."
	@python3 $(RECONV_SCRIPT) \
		--input $(DUMP_ASM) \
		--asm-out $(RECONV_ASM) \
		--mem-out $(RECONV_MEM) \
		--report-out $(RECONV_REPORT)
	@touch $@

$(RECONV_ASM) $(RECONV_MEM): $(RECONV_STAMP)
	@true

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
		$(RECONV_ASM) \
		$(RECONV_MEM) \
		$(RECONV_REPORT) \
		$(RECONV_STAMP) \
		$(NATIVE_EXE)

# ==========================================
# Phony targets
# ==========================================
.PHONY: all riscv x86 reconvergence clean
