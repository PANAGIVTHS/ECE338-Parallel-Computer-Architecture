# Parameterized multiplier

`Multiplier.LATENCY` counts registered stages **after EX**, not EX itself and not
the subsequent EXMEM/MEMWB registers. The arithmetic and `mul_stage_t` arrays
advance on the same edge with the same enable. Synchronous active-low reset takes
priority over global stall and clears every stage. Products retain the original
`word_t` truncation, including on invalid cycles. The initiation interval is one
unstalled cycle, independent of latency.

A replacement DSP/IP implementation must provide the same latency, initiation
interval, global clock-enable/freeze behavior, and reset behavior. Merely matching
its nominal latency is insufficient. Only the arithmetic implementation inside
`Multiplier` should need replacement; its metadata and hazard interface remain.

The hazard array contains only registered stages. EX remains a separate check.
Non-MUL issue blocking, the independent-MUL exception, the original EX-destination
comparison, load-use priority, and branch flush priority are preserved. `x0`
validity is still determined in `StreamingProcessor`; the multiplier transports
metadata without reinterpreting it. Branch feedback remains in `sp_feedback_t`;
MUL hazards use a separate parameterized port, and shared control still uses core 0.

## Intentionally unchanged

The existing MUL/DIV detection treats every R-type instruction with
`FUNCT7_MULDIV` as multiplication, as already noted in the RTL. The existing
hazard exception also compares ID sources against `i_idex_rd` unconditionally,
even when only registered MUL stages are pending.
