# The system block design

`design_1.tcl` is the source of truth for the block design. A new project is built
from it, and it is a plain `write_bd_tcl` export, so **do not edit it for its
comments**: `gpgpu project pull system` regenerates it.

```bash
./gpgpu project open system     # edit the design in Vivado, save, close
./gpgpu project status system   # see what changed
./gpgpu project pull system     # write it to design_1.tcl, once a rebuild proves it identical
git diff hardware/bd/design_1.tcl
```

Editing the script by hand also works: `gpgpu project push system` applies it to the
project. `tools/gpgpu/adapters/vivado/tcl/configure_block_design.tcl` is applied over it
on every build, because the configuration owns the core count, the CSR aperture and the
fabric clock.

## Why the design is the way it is

**PS inputs.** Transcribed from the board's saved design. Computed `PCW_ACT_*` and clock
outputs are Vivado's. SD0 is the TF card on MIO 40..45, the only SD boot pins the BootROM
supports, with card detect on MIO 47 and no write protect. The FSBL needs it to read the
bitstream and the host from `BOOT.BIN`; bank 501 is 3.3 V. FCLK_CLK1 is 100 MHz, which the
PS makes exactly (I/O PLL / 10). `PCW_EN_CLK1_PORT` creates its pin; the enable alone does not.

**Two masters reach PS DDR**, each through its own HP port so that they meet only in the
DDR controller (HP0/HP1 and HP2/HP3 share its ports): the GPGPU's `m00_axi` on HP0 and the
VDMA on HP2. Each has a 1x1 SmartConnect, which also converts AXI4 to the HP port's AXI3.
Both see the PS DDR identity-mapped. GP0 reaches the GPGPU's CSRs, GP1 the VDMA's registers.

**Scanout.** A read-only VDMA of 32-bit pixels (one framebuffer word each), two frame stores
(FB0, FB1), 16-beat bursts -> 4-to-3-byte subset converter (`0x00RRGGBB` to the 24-bit
AXI4-Stream video order {R, B, G}) -> AXI4-Stream video out, timed by a VTC in its default
mode -> `rgb2dvi`. The video out is the VTC’s slave: its vtg_ce drives the VTC’s gen_clken,
so the timing waits for the stream. The other clock enables are tied on, and the field id
is tied to 0 (progressive).

**Clocks.** FCLK_CLK0 is owned by the configuration and follows the GPGPU's timing, so it
runs only the GPGPU, GP0 and HP0. The display runs on the fixed FCLK_CLK1 (GP1, the VDMA, HP2
and the stream into the video out, faster than the pixel clock so the stream keeps up) and
on a 74.25 MHz (720p60) pixel clock made from the board's 50 MHz PL oscillator, not from a
PS clock: the PS PLLs jitter, and the oscillator sits in the HDMI bank. The video out's
asynchronous FIFO crosses from FCLK_CLK1 to the pixel clock.

`rgb2dvi` makes the 5x TMDS serial clock itself with an MMCM in the TMDS pins' clock region
(BUFIO for the serial clock, BUFR for the serializers' pixel clock), so the OSERDES clocks
stay off the global clock network the GPGPU's switching disturbs (see
[the HDMI investigation](../../docs/hdmi-blanking-investigation.md)). That region has one
MMCM, so `clk_wiz_0` is a PLL.

**Resets.** One per clock: `gpu_sys_reset` for FCLK_CLK0, `rst_ps7_0_35M` for FCLK_CLK1 and
`proc_sys_reset_0` for the pixel clock. All take FCLK_RESET0_N. The PS clocks need no lock,
so their `dcm_locked` is tied high.

**Interrupt.** `gpgpu_axi_0/irq` is bit 0 of the 16-bit fabric IRQ bus (PS interrupt ID 61).
