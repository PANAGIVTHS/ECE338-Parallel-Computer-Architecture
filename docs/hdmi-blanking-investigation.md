# HDMI blanking under GPU load: investigation notes

Status (2026-11-04): mitigated by a block-design change, no RTL change. The
GPU's switching corrupts the TMDS data on the link; the FPGA's video pipeline
itself never loses lock or sync. Clocking the serializers regionally
(rgb2dvi's own MMCM with BUFIO/BUFR in bank 34) keeps the Samsung monitor up
to at least 80 MHz GPU clock, except in a band around 30–36 MHz with the
heaviest ADD-chain load, and except one unexplained 10-minute bad state that
a bitstream reload cleared. See "Current recommendation" near the end.

(Earlier status: sink-dependent. The LG and Sharp TVs and the capture card
tolerate more than the Samsung monitors, and the TVs show particles.)

## Symptom

The HDMI monitor goes black while the GPU runs a compute-heavy kernel. It
comes back a few seconds after the load stops. Even a single short run of
about 20–70 ms can blank it "for a bit": the monitor loses sync and needs
time to detect the signal again.

The same HDMI output, recorded by the capture card on the Live-FPGA-Lab VM
(vm2), looks normal throughout. An LG TV shows it without blanking too.

## Setup

- Board: Smart Zynq SL (xc7z020clg484-1). One USB-C for power and UART; JTAG is
  a separate connector.
- GPU: 32 SPs on FCLK0 at 42.1 MHz (`hardware.vivado.fabric_clock_mhz: 42`),
  with DMEM/IMEM in BRAM. It writes the framebuffers in DDR through HP0.
- Display (FCLK1 = 100 MHz from the PS):
  - VDMA (HP2) → AXI4-Stream subset converter → `v_axi4s_vid_out` → `rgb2dvi` → TMDS_33 pins
    N19 / M21 / L21 / J21.
  - The VTC provides 720p60 timing.
  - `clk_wiz_0` (an MMCM fed from FCLK1) makes the 74.25 MHz pixel clock and, since the last
    change, the 371.25 MHz serial clock.
- The FPGA drives HDMI directly, with no redriver chip.

## Observations

### Ruled out

| Test | Result | Rules out |
|---|---|---|
| Ripple with one row per frame (`wdmem 12 1`), even with `bench 3000` | no blanking | the run/launch traffic itself |
| GPU writes FB0 while FB1 is displayed | blanks | the VDMA reading the frame the GPU is writing |
| VDMA 64-beat bursts and 8192-pixel line buffer; DDR HPR queue for HP2/HP3 with HPR critical level 1 | still blanks | DDR bandwidth or priority starving the scanout |
| Board on a wall charger instead of the PC's USB port | still blanks | the USB port's supply |
| Compute-only ripple (results summed, one store per frame) | blanks | DDR traffic in general |
| Ripple writing only into DMEM (BRAM), no DDR access at all | a single run blanks | AXI, DDR and the VDMA entirely |
| `v_axi4s_vid_out/locked` on LED P21 | stays lit while the monitor is black | loss of video timing; the pipeline stays locked |
| Serial clock from `clk_wiz_0` (`kGenerateSerialClk false`, `JITTER_SEL Min_O_Jitter`) instead of `rgb2dvi`'s own PLL | still blanks | the second, cascaded PLL as the main cause |

### XADC during the compute-only kernel (about 58 frames/s)

| Rail | Idle | Running (typical) | Running (minimum) |
|---|---|---|---|
| VCCINT | 993 mV | 984–996 mV | 978 mV |
| VCCAUX | 1803 mV | 1800–1804 mV | 1798 mV |
| VCCBRAM | 993 mV | 989–993 mV | 987 mV |

The die temperature rose from about 48 °C to 58.8 °C over roughly 80 s.

A slow sag of about 15 mV is well within spec (950–1050 mV), so there is no
gross supply failure. The XADC cannot see noise in the nanosecond range.

### Power estimate (`report_power`, routed design, FCLK0 at 40 MHz)

The default vectorless estimate gives the GPU only 18 mW: the enables and the
stall signal gate the propagated activity, so it shows the GPU idle. The
activity was therefore set on all 156,012 GPU signal nets:

| GPU activity | Vccint (1.0 V) | Total on-chip | GPU step on Vccint |
|---|---|---|---|
| vectorless (≈ idle) | 0.082 A | 1.74 W | — |
| 25 % toggle rate | 0.380 A | 2.03 W | +0.30 A |
| 50 % toggle rate (≈ random data) | 0.678 A | 2.34 W | +0.60 A |

Vccpint (PS core, 1.0 V) stays at 0.71 A, and Vcco33 (mostly TMDS) at 0.04 A.

Reading:
- Under random-data load the GPU draws an extra 0.3–0.6 A on the 1.0 V
  supply, switched on within microseconds. If Vccint and Vccpint share one
  regulator, that rail goes from about 0.8 A to 1.1–1.4 A.
- Dynamic power scales with the clock, so doubling FCLK0 roughly doubles the
  step.
- The estimate is rough: Vivado warns that the 50 % rate also toggles reset
  nets. But the order of magnitude supports the power-delivery explanation.

### GPU clock

| FCLK0 | Result |
|---|---|
| 42 MHz | blanks under compute load |
| 20 MHz | no blanking |

This scales with switching current, but a lower clock is not acceptable as the
fix: the plan is to raise the clock after timing optimization.

### Kernels

| Kernel | Blanks | Notes |
|---|---|---|
| ripple, compute-only ripple, ripple into DMEM | yes | wide values that change almost every bit (`distance2`, colors) |
| nbody-3d (1 step, and 1000 steps per run, about 40 ms) | no | small values (positions ±256, masses 1–4): most bits stay constant |
| mandelbrot | — | hung, see the side findings |

### Stress kernel (`software/programs/stress/stress.c`)

Each mode runs one kind of activity. The seed sets data toggling with an
identical instruction stream: seed 0 keeps all data at zero, while
0x9E3779B9 and 0x9E3779A7 toggle about half the bits.

| Mode | Activity | Seed 0 | Random seed |
|---|---|---|---|
| 0 loop | counter and branch | no | no |
| 1 alu | xorshift32: shifts and `xor`, dependent | no | **blanks** |
| 2 mul | `mul` (first a dependent chain, then 8 independent back to back) | no | no |
| 3 dmem | `lw`, `xor`, `sw` on DMEM | no | **blanks** |
| 4 ddr | one 32-word burst to DDR per iteration | no | no |
| 5 xor | dependent `xor` chain | — | **blanks** |
| 6 add | dependent `add` chain | — | **blanks** |
| 7 rot | rotate (`slli`, `srli`, `or`), dependent | — | no at `000C0000` iterations (≈0.5 s); **blanks** at `00120000` (≈0.7 s) |
| 8 xor-i | 8 independent `xor`s, operand B constant | — | no |
| 9 ring | `xor`s with both operands random, no forwarding | — | not run yet |
| 10 xconst | dependent `xor`, operand B constant | — | not run yet |

**Caveat:** the yes/no results came from runs of different lengths and stall
rates. Mode 7 blanks once the run is longer, so the blanking is probabilistic:
its rate rises with switching activity. "No" only means "not within this
run". No single unit has been identified as the culprit; an earlier
hypothesis that a random ALU operand B is the cause is unproven.

### Back-powering through HDMI

With the board's USB-C unplugged but the monitor still connected, the board's
power LED stays bright: the monitor feeds current into the board through the
HDMI cable. The capture card has not been checked for the same. On the V1.3
schematic no obvious path exists (the TMDS lines are AC-coupled, D24 blocks
HDMI_5V towards 5V_DC, and the AO3400 body diodes point the other way), so
either the board is an older revision or the path is elsewhere; to be
measured. Back-powering an unpowered FPGA through its I/O violates the power
sequencing rules and should be avoided.

### Firm conclusions

1. The trigger is data toggling in the fabric. The same instructions with
   data held at zero never blank, so the clock tree, pipeline control and AXI
   alone are not the trigger.
2. The effect scales with switching activity: the GPU clock, how many bits
   change, and the toggle rate. It is a matter of degree, not one specific
   unit.
3. The video pipeline keeps its timing (`locked` stays high). What degrades is
   the electrical HDMI signal: jitter or noise that the capture card tolerates
   and the monitor does not.
4. The multiplier (DSP slices) and DDR traffic contribute the least.
5. It depends on the sink: the capture card and an LG TV keep the picture
   under the same load; only the original monitor loses sync. The board's
   reduced-margin TMDS (see the schematic section) is good enough for them.

### Working model

The GPU's switching current causes fast supply and ground noise. The noise
probably reaches the HDMI signal by one or more of these paths:

- **Via the PS clock:** if VCCPINT shares a regulator with VCCINT, which is common
  on low-cost boards (still to check in the schematic), the PS PLL behind FCLK1
  jitters more under load. `clk_wiz_0` currently runs with high bandwidth
  (`Min_O_Jitter`) and passes input jitter through.
- **Locally:** noise at the MMCM, the `rgb2dvi` OSERDES and the TMDS_33 output
  drivers, if the GPU logic is placed nearby.
- **Thin margin:** directly driven TMDS_33 without a redriver leaves little
  margin, so a stricter monitor drops out first.

### Board schematic (Smart Zynq SL V1.3, hellofpga.com)

- **A PL oscillator exists:** X2, 50 MHz, net `CLK_50M` on pin **M19**
  (`IO_L13P_T2_MRCC_34`). That is a clock-capable pin in bank 34, the HDMI
  bank (clock region X1Y1). The 33.333 MHz oscillator X1 feeds only the PS.
- **Power:** five TPS563210A bucks (3 A each) from 5 V_DC: VCC1V0, VCC1V5,
  VCC1V8, VCC3V3 and VADJ. VCC1V0 alone supplies VCCINT, VCCPINT and VCCBRAM.
  At an estimated 1.1–1.4 A under load it is not overloaded; the question is
  its transient response and decoupling.
- **HDMI:**
  - Sheet 4 (V1.3): each TMDS line has a 49.9 Ω pull-up to VCC3V3 on the
    FPGA side, then a series 0.1 µF capacitor to the connector, plus PUSB3FR4
    ESD arrays. So the output is AC-coupled and source-terminated, not the
    DC-coupled TMDS of the HDMI specification. That reduces the swing and
    leaves the sink to set the common mode. It works with most sinks, but with
    less margin.
  - DDC and HPD go through AO3400 level shifters to HDMI_5V. HDMI_5V comes
    from 5V_DC through D24 (1N4148).
  - VCCO_34 is VCC3V3, and HDMI_5V comes from 5 V_DC.
  - The HDMI clock pins differ between board revisions (N19/N20 or N22/P22).
    This board works on N19, so the XDC matches its revision.

## Fixes tried

| Change | Result |
|---|---|
| VDMA burst 64, line buffer 8192 | no effect on the blanking (kept: more DDR headroom) |
| DDR controller: HP2/HP3 reads in the HPR queue, HPR critical level 1, LPR/write 15 | no effect on the blanking (kept) |
| Wall charger | no effect |
| Serial clock from `clk_wiz_0`, `Min_O_Jitter`, `kGenerateSerialClk false` | no effect (kept: one PLL fewer) |
| FCLK0 at 20 MHz | fixes it, but not acceptable as the solution |
| `clk_wiz_0` `JITTER_SEL Max_I_Jitter` (low bandwidth), FCLK0 at 40 MHz in the same build | still blanks under the standard trigger (kept for now) |
| `clk_wiz_0` from the 50 MHz PL oscillator (`clk_50m`, M19) instead of FCLK1 (`clk_out1` 13.474 ns, `clk_out2` exactly 1/5) | still blanks: the PS clock is not the path (kept) |
| Another sink: an LG TV, same build and load | **works perfectly**: the blanking is specific to the original monitor |

## Best candidates

Ranked by cost and likelihood. Evaluate each one with the standard trigger
(below).

1. **`clk_wiz_0` with `JITTER_SEL Max_I_Jitter`** (bandwidth LOW, filters input
   jitter). One property, one rebuild:
   ```tcl
   set_property CONFIG.JITTER_SEL {Max_I_Jitter} [get_bd_cells clk_wiz_0]
   ```
   It helps if the jitter comes in through FCLK1. **Tried: still blanks.** So
   jitter on FCLK1 is at least not the only path; the local paths are now the
   more likely ones.
2. **A clean display clock: the 50 MHz PL oscillator on M19.** It is in the
   same bank and clock region as the HDMI pins. `clk_wiz_0` takes it instead
   of FCLK1, and the MMCM can sit in X1Y1 next to the OSERDES. This takes the
   PS PLL out of the display path entirely. Exactly 74.25 MHz is probably not
   achievable from 50 MHz with one MMCM, but HDMI sinks tolerate ±0.5 %. The
   commented-out Y9 "100 MHz" in `smart_zynq.xdc` comes from a ZedBoard
   template and does not apply.
3. **Floorplanning:** a pblock that keeps the GPU out of the clock region of
   the HDMI pins, the MMCM and the `rgb2dvi` serializers. Gather first, in the
   implemented design:
   ```tcl
   foreach p {N19 M21 L21 J21} {
       set site [get_sites -of_objects [get_package_pins $p]]
       puts "$p bank [get_property BANK [get_package_pins $p]] region [get_clock_regions -of_objects $site]"
   }
   puts "MMCM: [get_property LOC [get_cells -hier -filter {REF_NAME == MMCME2_ADV}]]"
   ```
   plus a screenshot of the Device view with `gpgpu_axi_0` highlighted.
4. **Reduce switching activity in the RTL:** operand isolation in `ALU.sv`
   (only the active unit sees the operands; today the adder, shifter and
   comparators all compute every operation), and clock enables or held
   inputs for idle units. This also lowers power at higher clocks. Ruled out
   for now: the RTL should not be changed for a board problem.
5. **A cheap check:** an HDMI splitter or repeater (they usually regenerate the
   signal), plus another cable or monitor. **Another sink tried: an LG TV
   works**, which confirms the "marginal signal" explanation. For the original
   monitor, a repeater or splitter is the practical fix; it is not a fix for
   the board itself.

## Lab session 2026-11-03 (automated)

### Rig

- **Sink:** Samsung C32R50x (HDMI 1.4, slightly damaged panel), the same
  short cable throughout.
- **Board power and UART:** the board's USB-C on the Raspberry Pi 5
  (`/dev/ttyUSB0`, CH340). The Pi allows 1.6 A on USB
  (`usb_max_current_enable=1`); its own 5 V input (`vcgencmd pmic_read_adc
  EXT5V_V`) is logged every 0.5 s during each trial.
- **JTAG:** a Digilent FT232H cable (reports itself as "Digilent USB Device")
  on the Pi, driven by OpenOCD with the HS2 pin layout and
  `target/zynq_7000.cfg`. It halts CPU0, reads and writes memory and SLCR
  registers, and resets the board (SLCR unlock, `PSS_RST_CTRL`). CPU1 sits in
  the BootROM and does not examine; target CPU0 only.
- **Camera:** the laptop's IPU6 camera through libcamera, aimed at the
  monitor, streamed as 160×100 grayscale at 30 fps. A trial logs the mean
  brightness of the screen region per frame with Unix time stamps. The Pi
  and laptop clocks agree to about 0.1 s.
- **Trial:** baseline brightness before the trigger command; *dark* is a
  frame below 40 % of the baseline. Reported: time from the trigger to the
  first dark frame, dark time during the load and in total, the Pi's 5 V.
- **Static picture:** `pixels` (three vertical bars) drawn into FB1 and
  shown with `display 1`. The stress kernel never writes the framebuffer, so
  tearing is impossible and any change on screen is a transmission error.
- **Stress kernel lane range:** the mode word's bits 15:8 are the first lane
  and bits 23:16 the number of lanes whose data toggles (0: all). The other
  lanes run the same instructions on zero data.

### Results

| Trial | Result |
|---|---|
| Idle, static bars, 15 s | no dark frame |
| Standard trigger (mode 1, 0x800000 iterations, seed 0x9E3779B9), 10.7 s | dark 0.36 s after the start; 8.3 s dark during the load, 10.4 s in total (about 2 s to resync after the load); Pi 5 V 5.10–5.11 V |
| Photos during a 32 s load | first black with no on-screen message; 5 s later the picture is back, with a horizontal error streak in the red bar: under load the monitor cycles between dropping and resyncing, and the picture between drops has corrupted pixels |
| UART during load, seed 0 and seed 0x9E3779B9 | no junk received. The junk seen earlier came from a minicom session left open on the laptop |
| FCLK0 sweep, one trial per clock (FPGA0_CLK_CTRL written over JTAG at runtime) | 20 and 25 MHz: never dark; 26.67–40 MHz: 98 % dark. A single pass; see the repeats below before trusting the sharp edge |
| Lane ranges at 40 MHz, first pass | 1–31 lanes never dark, 32 dark. **Not reproducible:** in the repeat, 31 lanes blanked 26.5 % and 91.7 %, 32 lanes 53–88 %. Single trials drift a lot over the evening |

Conclusion so far: single trials are not enough. The rounds below repeat
every condition, interleaved, with the die temperature and VCCINT.

### Repeated rounds

The die stays at 57–58 °C throughout. VCCINT (XADC, sampled during the
load) drops from 0.99 V to 0.976–0.984 V under any GPU load, whether the
monitor blanks or not, so its average level is not the trigger. The Pi's
5 V stays at 5.09–5.12 V.

| Condition (dark share of the load) | Round 1 | Round 2 | Round 3 |
|---|---|---|---|
| Idle | 0 % | | |
| 40 MHz, seed 0 (no toggling) | 0 % | 0 % | |
| 40 MHz | 94.8 % | | |
| 30.77 MHz | 98.6 % | | |
| 26.67 MHz | 98.6 % | | |
| 25.00 MHz | 0 % | | |
| 20.00 MHz | 0 % | | |
| GPU ripple, 300 frames into the shown FB1 | 93.7 % | | |

(Round 2 was cut short by a Wi-Fi drop to the laptop; the harness now
retries and runs the camera logger detached.)

Picture on screen, standard trigger at 40 MHz:

| FB1 shows | Dark share of the load |
|---|---|
| bars | 52 %, 84 %, 70 % |
| ripple frame | 0 %, 69 %, 0 % |
| white | 78 %, 52 % |
| gray 0x808080 | 79 %, 63 % |
| 1-pixel black/white checkerboard (`fill`) | 71 %, 76 % |

**ARM ripple (GPU idle), 40 frames, 13.9 s: 0 %, 0 %.** Rendering on the
PS, with its DDR writes into the shown framebuffer, does not blank. The
trigger needs the GPU switching in the fabric.

### Clock-ratio hypothesis

The edge between 25.0 and 26.67 MHz is sharp, but the switching current
differs by only 7 %. Candidate explanation: the beat between a harmonic of
the GPU clock and the 74.22 MHz pixel clock. 3 × 25 MHz is 0.8 MHz from the
pixel clock, slow enough for the sink's clock recovery to follow; 3 × 26.67
MHz is 5.8 MHz away. Test: 37.21 MHz (1600/43; 2× is 0.2 MHz from the pixel
clock) has almost the switching current of 40 MHz but should stay up.

**Refuted.** Two interleaved rounds of the standard trigger on bars:

| FCLK0 | Nearest harmonic to the pixel clock | Round 1 | Round 2 |
|---|---|---|---|
| 40.00 MHz | 2×, 5.78 MHz off | 67 % | 79 % |
| 38.10 MHz | 2×, 1.97 MHz off | 98 % | 79 % |
| 37.21 MHz | 2×, 0.20 MHz off | 81 % | 82 % |
| 36.36 MHz | 2×, 1.49 MHz off | 99 % | 99 % |
| 26.67 MHz | 3×, 5.78 MHz off | 99 % | 99 % |
| 25.40 MHz | 3×, 1.97 MHz off | 50 % | 0 % |
| 25.00 MHz | 3×, 0.78 MHz off | 0 %, 0 % | 0 %, 0 % |
| 24.62 MHz | 3×, 0.37 MHz off | 0 %, 0 % | 0 %, 0 % |

What remains is a threshold in switching activity: at 25.0 MHz and below
never (8 of 8 runs in this test, plus the earlier rounds), 25.4 MHz
borderline, 26.67 MHz and above nearly always. VCCINT drops by the same
10–18 mV at every clock, so the average supply level is not the trigger;
fast noise or the coupling path is.

Additional picture rounds (the content campaign ran twice more by accident):

| FB1 shows | All runs, dark share |
|---|---|
| bars | 52, 84, 70, 0, 77 % |
| ripple frame | 0, 69, 0, 0, 0, 0 % |
| white | 78, 52, 26, 26, 26 % |
| gray | 79, 63, 26, 0, 27 % |
| black/white checkerboard | 71, 76, 98, 87, 65 % |
| ARM ripple, GPU idle | 0, 0, 0, 0 % |

The ARM never blanks the monitor. The picture matters somewhat: a ripple
frame on screen rarely blanks, the 1-pixel checkerboard nearly always.

**Fast ARM ripple.** The uncached version above writes only about 11 MB/s
(3 frames/s), far below the GPU ripple's 82 MB/s (22.3 frames/s). A cached
variant (`-DCACHED`) runs under the host app's MMU and caches: the I-cache is
invalidated before the start, and after each frame the framebuffer is
cleaned out of L1 (DCCMVAC) and L2 (PL310 Clean Line by PA), because the VDMA
reads DDR through an HP port that does not see the caches. It draws 46.5
frames/s (21.5 ms per frame), about 170 MB/s: twice the GPU's rate.

| Run | Dark share |
|---|---|
| Cached ARM ripple, 600 frames, 13.4 s | 0 % |
| Cached ARM ripple, 600 frames, 13.4 s | 0 % |

### Placement and the bitstream

Development loop without the SD card: build on the laptop (njason@xps,
Vivado 2025.2, `./gpgpu run vivado:system:build`, about 20 minutes), load
the PL over JTAG from the Pi (`openFPGALoader -c digilent_hs2 file.bit`),
then the host's `reset` reinitializes the PL side. The UART runs through
the PL (EMIO), so it delivers junk while the PL configures; resync after.

Region analysis of the laptop baseline (routed, `regions.tcl`): clock region
X1Y1 holds the HDMI pins (bank 34, N19/M21/L21/J21), the MMCM and all eight
`rgb2dvi` OSERDES, and 10,156 of its LUTs (98 %) are GPU logic. The rest of
the HDMI chain (`v_axi4s_vid_out`, `v_tc`) sits in X1Y2.

Keep-out experiment: a pblock `SLICE_X88Y50:SLICE_X113Y99` with
`EXCLUDE_PLACEMENT`, holding only `rgb2dvi`'s fabric logic, cut the GPU's
share of X1Y1 to 4,694 LUTs (WNS −0.41 ns at 42 MHz).

| Bitstream (standard trigger, dark share) | 16.67 MHz | 20 MHz | 25 MHz | 40 MHz |
|---|---|---|---|---|
| SD card (the user's build, `INFO_CLOCK` 40 MHz) | | 0 %, 0 %, 0 % | 0 % ×4 | 94 %, 97 % |
| Laptop baseline (repo bootstrap, built for 42 MHz) | 99 % | 99 % | 99 %, 99 % | 99 %, 99 % |
| Laptop + keep-out pblock | 99 % | 99 % | 99 % | 99 % |

With every laptop bitstream, idle and seed 0 never blank. **The same RTL
blanks at any clock from 16.67 MHz up in the laptop builds, but only above
25 MHz in the user's build.** The keep-out made no difference, so the GPU's
proximity to the TMDS outputs is not the mechanism. Candidates: the build's
target clock (42 against 40 MHz), a difference between the user's GUI block
design and `create_block_design.tcl`, or JTAG against FSBL configuration.

Rebuilt on the laptop with `fabric_clock_mhz: 40` (WNS +0.012 ns) and loaded
over JTAG:

| Bitstream | 20 MHz | 25 MHz | 40 MHz |
|---|---|---|---|
| Laptop, built for 40 MHz | 0 %, 0 % | 0 %, 0 % | 79 %, 14 % |

It behaves like the SD card build, so JTAG loading and the bootstrap script
are fine; the build target is what differs. The GPU's placement is nearly
the same in both laptop builds (about 10,000 GPU LUTs in X1Y1). What
differs: the 42 MHz build had **replicated the FCLK0 global buffer**
(`FCLK_CLK_0_BUFG_replica` on BUFGCTRL_X0Y31, next to the original on
X0Y16); the 40 MHz build has a single BUFG. A design built for 42 MHz that
blanks even when clocked at 16.67 MHz points at its structure, and the
clock distribution is the prime suspect. Next: a 42 MHz build without BUFG
replication, and the user's routed checkpoint for comparison.

Follow-up:

- The user's routed checkpoint (the SD card build) is identical to the
  laptop's 40 MHz build: the same LUT counts per clock region and a single
  FCLK0 BUFG. The repo flow reproduces the user's build exactly.
- `DONT_TOUCH` on the FCLK0 BUFG did not stop the replica: post-route
  `phys_opt_design` (AggressiveExplore) adds it at the end, and it drives
  only 6 loads. A symptom of the timing pressure at 42 MHz, not a plausible
  coupling path by itself.
- `CLOCK_KHZ` only feeds the `INFO_CLOCK` register, so the RTL behaves the
  same in both builds.

**The difference is in the implementation, placement and above all routing.**
The keep-out moved GPU logic away from the TMDS outputs but not GPU nets
routed through that area. The likely mechanism is crosstalk inside the chip
between switching GPU nets and the HDMI path (serial and pixel clock to the
OSERDES, the TMDS output paths, the MMCM). How strong it is changes with
every build, which explains the build dependence, the dependence on
switching activity, and the moderate influence of the picture.

Two checks on the routed designs (the user's good build against the bad
42 MHz build) do not support a simple version of it:

- GPU signal nets in the INT tiles that the HDMI clock nets touch: 106 in the
  good build, 2 in the bad one. A rough metric, but it points the other way.
- Static timing of the HDMI path is the same: hold slack into the OSERDES
  0.424 ns (good) against 0.620 ns (bad), in the pixel-clock domain 0.108 ns
  against 0.117 ns, setup at least 7.3 ns in both. A smaller timing margin
  in the bad build is not the explanation.

Open: why one implementation tolerates the GPU's switching up to about
25 MHz and another not even at 16.67 MHz. Two builds are only two samples;
the difference may be as random as a placement seed.

Twice the GPU's framebuffer write rate from the PS does not blank the
monitor. The DDR traffic, the HP-port and DDR-controller load and the PS
activity are ruled out as the trigger; the GPU's switching in the fabric is
what matters.

### ARM ripple

The GPU kernel's `ripple_color()` compiled for the Cortex-A9
(`arm-none-eabi-gcc`, bare metal, at 0x1F000000) draws frames into FB1 while
the GPU stays idle. It is written to DDR over the AHB-AP; CPU0 runs it with
its MMU and caches off and IRQ/FIQ masked, then stops at a `bkpt`. About 3
frames/s (the GPU ripple: 22.3 frames/s). The host app is lost; a system
reset over the AHB-AP brings it back.

### JTAG pitfalls (OpenOCD 0.12, this cable)

- The cable's product string is "Digilent USB Device", not the "Digilent
  Adept USB Device" that `interface/ftdi/digilent-hs2.cfg` matches; use the
  same layout without the description.
- Memory, SLCR and XADC: use a `mem_ap` on AP 0 (AHB-AP). It needs no CPU,
  halts nothing, and works while both cores fail to examine.
- A session cut off during a transfer leaves DBGDSCR.ExtDCCmode (bits 21:20)
  in fast mode; every later examination of that core fails with "Error
  waiting for read dcc", and the core can stay halted (the UART goes silent).
  It survives a soft reset. Clear it through a `mem_ap` on AP 1 (APB-AP):
  DBGDSCR at 0x80090088 (CPU0) and 0x80092088 (CPU1).
- Loading code through CPU0 while the host app's MMU and caches are on did
  not land: the CPU fetched 0xFFFFFFFF and took the undefined-instruction
  exception.
- On the Pi 5, `uhubctl` switches the USB data connection but not the port's
  5 V, so it cannot power-cycle the board.

### Night run 2026-11-04: layout variants

Six extra implementation runs on the same synth_1 (40 MHz build), each with
its own placement directive (`variants.tcl`: `create_run -parent_run
synth_1`, post-route phys_opt AggressiveExplore as in impl_1), loaded over
JTAG, standard trigger on bars, one trial per clock:

| Variant (`place_design` / `route_design`) | 25 MHz | 26.67 | 30.77 | 35.56 | 40 MHz |
|---|---|---|---|---|---|
| v0 Default / Default (= the user's build) | 0 % | 99 % | 99 % | 99 % | 90 % |
| v1 Explore / Explore | 0 % | 99 % | 99 % | 99 % | 85 % |
| v2 ExtraNetDelay_high / Default | 16 % | 99 % | 99 % | 99 % | 0 % |
| v3 ExtraPostPlacementOpt / Default | 0 % | 99 % | 99 % | 99 % | 98 % |
| v4 AltSpreadLogic_high / Default | 94 % | 99 % | 99 % | 99 % | 99 % |
| v5 ExtraTimingOpt / Default | 0 % | 99 % | 99 % | 99 % | 89 % |
| v6 EarlyBlockPlacement / Default | 75 % | 99 % | 99 % | 99 % | 94 % |

No placement strategy fixes it. (`SpreadLogic_high` is not a valid placer
directive in 2025.2.) 40 MHz is often less bad than 26.67–35.56 MHz.

### Regional HDMI clocks (step 2)

`regional.tcl` on a copy of the project: `clk_wiz_0` becomes a PLL (one
MMCM per clock region) making only the 74.25 MHz pixel clock;
`rgb2dvi_0` gets `kGenerateSerialClk true`, `kClkPrimitive MMCM`,
`kClkRange 2`. rgb2dvi's own MMCM (MMCME2_ADV_X1Y1) then drives the OSERDES
`CLK` from BUFIO_X1Y5 and `CLKDIV` from BUFR_X1Y5, inside bank 34: the
serializer clocks leave the global clock network. Timing met, WNS +0.019 ns.

Right after loading it over JTAG:

| Test | Result |
|---|---|
| Standard trigger, 25 / 26.67 / 30.77 / 35.56 / 40 MHz, two rounds | 0 % in all 10 |
| Photo during a 32 s load at 40 MHz | clean bars |
| 40 MHz on checkerboard, white, ripple frame, bars | 0 % each |
| Positive control: v0 reloaded, 30.77 and 40 MHz | 98.6 %, 97.6 % (the rig is still sensitive) |

Then, after about 10 minutes, the same build blanked again:

| Test (40 MHz) | Result |
|---|---|
| Modes 5 and 6 | 97 %, 97 % |
| Mode 1 for 60 s | 80 % |
| GPU ripple, 600 frames | 96 % |
| Mode 1, three repeats | 81 %, 98 %, 62 % |
| After the host's `reset` (PL reset), four repeats | 52 %, 80 %, 55 %, 75 % |
| **After reloading the bitstream**, four repeats | **0 % ×4** |
| Then mode 1 ×2, mode 5, mode 1 ×2 | 0 % ×5 |
| Then mode 3 for 64 s, mode 1 ×2 | 0 % ×3 |

**A hidden state decides.** It survives the PL reset but not a
reconfiguration of the PL, and in its good state the regional build stays up
under every load tried. Neither mode 5 nor a long mode 3 run flips it into
the bad state; the trigger of the flip is not known yet.

Later runs in the good state:

| Test | Result |
|---|---|
| Endurance: standard trigger, alternating 40 and 30.77 MHz, 30 trials over 28 min | 0 % in all 30 |
| Replay of the sequence before the flip (v0 control, reload regional, four pictures, a mode 3 run cut off by the script's timeout, reconnect, modes 3/5/6, mode 1 ×3) | v0 98.8 % / 82.2 %, regional 0 % in all 10 |

In total the regional build stayed up in about 70 trials across all modes,
pictures and runs up to 64 s; the bad state showed once, for about 10
minutes (02:38–02:48), and reloading the bitstream ended it.

### Does the pixel clock lose lock? (probe build)

Hypothesis: `clk_wiz_0` has no reset (`USE_RESET false`); if its MMCM lost
lock under the GPU's noise, `proc_sys_reset_0` (via `dcm_locked`) would reset
the whole HDMI chain, the TMDS outputs would stop, and the monitor would
resync for seconds.

Probe build (`irq_probe.tcl`, the base layout plus two inverters, no RTL):
`IRQ_F2P[1]` (ID 62) ← NOT `clk_wiz_0/locked`, `IRQ_F2P[2]` (ID 63) ← NOT
`v_axi4s_vid_out_0/locked`. Findings on reading them:

- An ILA read out over XVC did not work: Vivado connects to
  `openFPGALoader --xvc` (port 3721, needs an open stdin or it crashes with
  "bit out of range 0 - FD_SETSIZE"), but finds no device on the chain.
- `irq_concat` rejects a reset-type pin (`peripheral_reset`), and an
  `ilvector_logic` inverter takes its input's type, so the HDMI reset itself
  could not be probed.
- The GIC (Cortex-A9 private region) is not reachable over the AHB-AP, only
  through a CPU. It latched no pending state for these interrupts, neither
  disabled nor enabled with no CPU target, so the probe reads the raw levels
  (`ICDSPI_STATUS`, 0xF8F01D04) through CPU1 in a polling loop (`cortex_a smp
  off`, or halting CPU1 also halts the host app on CPU0). About 160 samples
  per second.
- Self-test: a 50 ms `FCLK_RESET0` pulse (SLCR `FPGA_RST_CTRL`) shows "video
  out lost sync" in 321 of 488 samples.

| Run (base layout, 40 MHz) | Dark | Samples | clk_wiz_0 lost lock | Video out lost sync |
|---|---|---|---|---|
| Standard trigger | 95.4 % | 2,951 | 0 | 0 |
| Standard trigger | 94.5 % | 2,965 | 0 | 0 |
| Standard trigger | 85.5 % | 2,978 | 0 | 0 |
| Seed 0 | 0 % | 2,967 | 0 | 0 |

**The FPGA-side video pipeline runs without interruption while the monitor
is dark.** The pixel clock never loses lock and the video output never loses
sync. The damage is on the TMDS link itself: the serial data reaches the
sink corrupted enough to lose sync. This fits everything else: the particles
on the TVs, the dependence on switching activity and on the layout, and the
large improvement from regional serializer clocks (BUFIO/BUFR in bank 34),
which take the OSERDES clocks off the global clock network that the GPU's
clock shares.

### Headroom of the regional build

The GPU clock pushed past timing closure (the design meets timing at 40 MHz;
above that the GPU's results may be wrong, but the switching activity is
there and the run times scale with 1/f), standard trigger on bars:

| FCLK0 | 42.11 | 44.44 | 47.06 | 50.00 | 53.33 | 57.14 | 61.54 | 66.67 | 72.73 | 80.00 MHz |
|---|---|---|---|---|---|---|---|---|---|---|
| Dark | 0 % | 0 % | 0 % | 0 % | 0 % | 0 % | 0 % | 0 % | 0 % | 0 % |

In its good state the regional build keeps the monitor up to at least
80 MHz. The old layout blanks from 26.67 MHz.

### A remaining band: 30–36 MHz with ADD chains

Second endurance run on the regional build (36 trials, mixed modes and
clocks): every combination stayed at 0 % except **mode 6 (dependent ADD
chain) at 30.77 MHz: 98 % in 6 of 6**. A sweep of mode 6:

| FCLK0 (MHz) | 25.00 | 26.23 | 26.67 | **30.77** | **32.00** | **35.56** | 40.00 | 42.11–100 (12 steps) |
|---|---|---|---|---|---|---|---|---|
| Mode 6, dark | 0 % | 0 % | 0 % | **97 %, 98 %** | **97 %** | **83 %** | 0 % | 0 % each |

Mode 1 at 30.77 MHz stays at 0 %, and so does mode 6 at 40, 50 and 66.7 MHz
in 10–16 s runs. So there is a **frequency band around 30–36 MHz** in which
the GPU's strongest current pattern (carry chains switching every cycle)
still breaks the link, even with regional clocks. A resonance of the core
supply's power distribution network in that range would explain it, and it
also explains why the old layout was at 99 % from 26.67 to 35.56 MHz but
often less at 40 MHz.

Practical consequence: run the GPU above the band. 40 MHz and every clock
tried up to 100 MHz stay up with the regional build.

### Current recommendation

Use rgb2dvi's own clocking for the serializers (no RTL change, block design
only):

1. `rgb2dvi_0`: `kGenerateSerialClk true`, `kClkPrimitive MMCM`,
   `kClkRange 2` (pixel clock of 60 MHz or more), `SerialClk` unconnected.
2. `clk_wiz_0`: `PRIMITIVE PLL` (the clock region has one MMCM, which rgb2dvi
   now uses), only `clk_out1` at 74.25 MHz.

3. Keep the GPU clock out of 30–36 MHz (40 MHz is fine).

Open points: the bad state seen once (cleared by reloading the bitstream;
possibly `clk_wiz_0`'s PLL, which nothing but a reconfiguration resets). A
variant with `CONFIG.USE_RESET true`, `CONFIG.RESET_TYPE ACTIVE_LOW` and
`clk_wiz_0/resetn` on `FCLK_RESET0_N` is built
(`~/hdmi-lab/builds/regional_reset.bit` on the laptop) but untested, since
the bad state could not be reproduced. Also open: repeating the measurement
on the other monitors and TVs, and a USB power meter or scope on the board
to confirm the resonance.

## How to measure

- **Standard trigger:** stress mode 1, seed 0x9E3779B9, buffer 0x1000, a run of
  about 10 s:
  ```
  wdmem 10 00000001
  wdmem 11 00800000
  wdmem 12 9E3779B9
  wdmem 13 00001000
  bench 1
  ```
  `bench 1` reports the real duration of the run.
- **Metric:** time until the monitor blanks (or "nothing in 10 s"), three
  repetitions. Compare against the current state for each fix.
- **Mode ranking:** the same procedure per mode at about 10 s each, with
  iterations ≈ 420 M / instructions per iteration (at 42 MHz, about one
  instruction per cycle). Instructions per iteration: loop 2, alu 50, mul 10,
  dmem 26, ddr 9, xor 18, add 18, rot 26, xor-i / ring / xconst 10.
- **Optional:** a USB-C power meter between the charger and the board, to
  measure the switching current (mode 1 with seed 0 against the random seed).
  Also `report_power` of the implemented design.

## Temporary state in the tree (uncommitted)

- The block design and `tools/hardware/vivado/create_block_design.tcl`:
  `v_axi4s_vid_out_0/locked` drives `o_core_running_0` (P21) instead of
  `gpgpu_axi_0/o_core_running`. Revert it once the test is no longer needed.
- `software/programs/stress/`: a new stress kernel with modes 0–10.

## Side findings

- **`auipc` hang:** the GPU has no `auipc`. `Decoder.sv` runs unknown opcodes
  silently as `add`, so a call that isn't inlined (`auipc` + `jalr`) jumps into
  empty IMEM and restarts the kernel forever. mandelbrot was affected; fixed
  with `always_inline` on `mandel_pixel`; that fix has since been discarded
  from the tree, so mandelbrot hangs again until it is re-applied. Proposed: a build check that rejects
  `auipc`, or a decoder fault on unknown opcodes.
- **Jump tables:** GCC places switch/if-chain jump tables in `.rodata` (DMEM),
  which is never filled when only IMEM is loaded. The stress kernel uses
  `optimize("no-jump-tables")`.
- **nbody-3d:** `reset` does not initialize `mass[]`, and `fpga.py` does not
  write it, so the bodies fly without force unless the masses are written
  manually (DMEM words 0x4C0–0x4DF).
- **Timing:** at 42 MHz, WNS −0.076 ns / TNS −0.356 ns, all in the DDRBackend.
  This is independent of the blanking, but has to be fixed for higher clocks.
- **Python tests:** 13 tests (FPGA programs, UART protocol, fake-Vivado
  `system:create`) fail here with and without these changes; they were not
  investigated.
