# RTL organization

Keep the hardware easy to follow: use types for real interfaces and instruction
layouts, and functions where they simplify bit manipulation or repeated packet
initialization. Do not wrap ordinary wiring, comparisons, or muxes merely to name them.

## Instruction decode

`riscv_pkg.sv` defines `instruction_t`, a packed union with raw bits and named
R/I/S/B/U/J layouts. `Decoder.sv` reads these fields directly:

```systemverilog
instruction_t instruction;
assign instruction.bits = i_instr;

// Inside the decoder's combinational block:
o_decoded.rs1 = instruction.r.rs1;
o_decoded.imm_31_20 = instruction.i.imm;
```

Field assignments and opcode/ALU case tables stay together in the decoder.
ECALL overrides the semantic source to x17 so ordinary hazards and forwarding
handle its implicit dependency. The encoded instruction is not rewritten.

## Immediate decoding

The five `immediate_i/s/u/b/j` functions in `riscv_pkg.sv` handle sign extension
and split immediate encodings. Execute calls them directly; there is no extra
immediate-result struct or decode-packet construction layer. Existing compact ID/EX
fields and all pipeline packet layouts are unchanged. For S/B instructions,
`rd` carries encoded immediate bits, not a write destination.

## Keep local logic local

- Forwarding priority and operand muxes are explicit in their modules.
- Hazard logic uses local named conditions, not package-level comparison helpers.
- Branch conditions, target arithmetic, and JALR link selection remain visible
  in Execute. Operand selection stays before the shared addition, preserving
  unknown-value propagation as well as ordinary binary results.
- Small `idex_bubble`, `exmem_bubble`, and `memwb_bubble` constructors in
  `pipeline_pkg.sv` share reset/bubble values. ID/EX defaults match reset;
  issued bubbles pass their PC and `ALU_OP_INVALID`. Single-field zero resets
  remain inline, as do all stall/advance decisions.
- Pipeline-busy feedback is a direct expression; no single-use activity struct.
- `pipeline_pkg.sv` contains pipeline interfaces, forwarding selectors and the
  small bubble constructors, not a general-purpose combinational wrapper layer.

No ISA, pipeline timing, memory protocol, or ECALL termination policy is changed.

## Verification

Existing commands and coverage are in `tests/hardware/rtl/readability/` and
`tests/hardware/rtl/ecall/`. The simplification was checked at 4 and 32 lanes:

- Decoder, forwarding, hazard, instruction-layout and immediate tests passed.
- All 29 directed programs matched the pre-refactor cycle traces exactly.
- Focused ECALL/compiled-C checks, SMX/AXI directed cases, and seeded random cases
  passed. No new lint diagnostics were introduced against the original baseline.
- Targeted SystemVerilog four-state evaluation passed for the local branch
  datapath, including ambiguous opcodes and unknown immediates/results.

Results: `build/tests/rtl-simplify-equivalence/results.json`,
`build/tests/rtl-simplify-functional/results.json`, and
`build/tests/rtl-readability/four-state/results.json`.
These are simulation, constant-evaluation and lint results, not synthesis,
FPGA execution, timing closure, or formal equivalence.
