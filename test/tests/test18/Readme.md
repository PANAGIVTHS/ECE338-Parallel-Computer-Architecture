# Test 19: BNE coverage

Focused regression test for the `bne` branch instruction.

Covers:

- equal operands: not taken
- unequal operands: taken
- zero/non-zero comparisons
- `x0` equality
- all-ones / negative-looking values
- high-bit values (`0x80000000` vs `0x7fffffff`)
- branch operands produced immediately before the `bne` to exercise forwarding
- backward `bne` loop with repeated taken branches and final not-taken exit
- self-comparison of a non-zero register

Each case writes an independent signature to DMEM so failures identify the exact
branch case. Expected successful signatures are:

| DMEM word | Expected |
| --- | --- |
| 0 | 1 |
| 1 | 2 |
| 2 | 3 |
| 3 | 4 |
| 4 | 5 |
| 5 | 6 |
| 6 | 7 |
| 7 | 8 |
| 8 | 9 |
| 9 | 10 |
| 10 | 5 |
| 11 | 12 |
