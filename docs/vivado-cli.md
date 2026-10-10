# Vivado CLI flow

The generated Vivado project is not tied to a checkout path. The CLI resolves
the repository root at runtime, references RTL from `hardware/rtl/`, and uses
`hardware/constraints/smart_zynq.xdc` from the same checkout.

## Prerequisite

Vivado 2026.1 must be available as `vivado`, or configured locally without
changing the shared profile:

```yaml
# config/local.yaml
tools:
  vivado:
    command: /opt/Xilinx/Vivado/2026.1/bin/vivado
```

`config/local.yaml` is ignored by Git.

## Stages

Each command depends on the stage above it, so invoking a later stage runs any
missing or out-of-date prerequisites automatically:

```text
vivado:project
  └─ vivado:block-design:build  (reuse/export saved BD, or bootstrap default)
       └─ vivado:block-design:run  (generate products and HDL wrapper)
            └─ vivado:synthesis
                 └─ vivado:implementation
                      └─ vivado:bitstream
                           └─ vivado:xsa
```

`architecture.num_cores` is the shared core-count setting. The RTL test flow
passes it to both testbench top-level parameters and expected-memory generation;
software-program builds receive it as the `GPGPU_NUM_CORES` C preprocessor
macro; and the Vivado block-design stage applies it to `GPGPU.SP_PER_SM` before
generating the HDL wrapper. Changing it invalidates the relevant task commands
and causes the software, RTL simulator, and Vivado synthesis artifacts to be
rebuilt.

The five AXI GPIO base addresses are also Vivado-owned configuration:

```yaml
hardware:
  vivado:
    host_interface:
      address_gpio: "0x41200000"
      cmd_gpio: "0x41210000"
      rdata_gpio: "0x41220000"
      status_gpio: "0x41230000"
      wdata_gpio: "0x41240000"
```

Each value must be a unique, 64-KiB-aligned 32-bit hexadecimal string. The
task layer passes them to every Vivado stage and the block-design flow applies
them to the matching `processing_system7_0/Data` address segments before BD
validation and wrapper generation. Changing one address invalidates the Vivado
command fingerprint and rebuilds downstream artifacts.

For a one-off command-line override, quote the YAML string value explicitly:

```bash
./gpgpu \
  --set 'hardware.vivado.host_interface.address_gpio="0x50000000"' \
  run vivado:all
```

Without the inner quotes, YAML interprets `0x50000000` as an integer and the
address-schema validation rejects it.

Run one stage with:

```bash
./gpgpu run vivado:project
./gpgpu run vivado:block-design:build
./gpgpu run vivado:block-design:run
./gpgpu run vivado:synthesis
./gpgpu run vivado:implementation
./gpgpu run vivado:bitstream
./gpgpu run vivado:xsa
```

`vivado:xsa` exports a fixed hardware platform with the bitstream included,
matching **File → Export → Export Hardware → Include bitstream** from the GUI.
It does not generate a separate configuration-memory binary and does not run
Vitis.

The aggregate command runs the complete chain through both output artifacts:

```bash
./gpgpu run vivado:all
```

## Default template and editable block design

After opening `build/hardware/vivado/GPU/GPU.xpr` in Vivado, editing
`gpgpu_block_design`, and saving the block design, close the GUI project before
running `vivado:all`.

`tools/hardware/vivado/create_block_design.tcl` is now the portable default /
exported **design template**, not the orchestration driver. Separate Tcl drivers
handle project setup, design preparation, export, and wrapper generation. The
old design-specific template filename is no longer used.

`vivado:block-design:build` has two branches:

- If the configured project already contains `gpgpu_block_design.bd`, reuse the
  saved design rather than deleting/recreating it. Export its normalized Tcl
  back to `create_block_design.tcl`, updating the template only when its content
  differs.
- If no saved block design exists, create the default design by sourcing the
  template in the managed project. A differently named existing design is an
  error rather than permission to silently replace it.

`vivado:block-design:run` depends on `:build` and generates the output products
and HDL wrapper, adds the wrapper to the project, and sets the top module. Here
`:run` means wrapper/output-product generation, **not** simulation, synthesis,
FPGA programming, or launching the GUI.

```bash
./gpgpu run vivado:block-design:build  # preserve/export or bootstrap the BD
./gpgpu run vivado:block-design:run    # also generate products and wrapper
```

The project stage preserves a valid saved BD as a normalized template before
any destructive project recreation caused by RTL/configuration changes. If
preservation/export fails, recreation stops before deleting the project.

**Precedence:** an existing saved BD in the configured build root wins over
manual edits to the template. A build can therefore modify a tracked source
file. Review the template diff before committing; close Vivado first so that
saved state and project locks are unambiguous. To use a manually changed default
without overriding an editable project, use a fresh build root. Unsaved GUI
changes cannot be exported by the CLI.

The flow checks for machine-specific absolute paths and compares normalized
content rather than timestamps. `architecture.num_cores` remains config-owned
and is normalized to `$::NUM_CORES` instead of being captured as a
machine/project-specific value.
Likewise, exported concrete AXI GPIO offsets are normalized to the corresponding
`$::HOST_*_GPIO` variables so a GUI export cannot replace configured addresses
with one project's snapshot values.

If the committed Tcl differs from the block design, the command prints a
warning and updates it atomically. If there is no difference, it reports that
the Tcl is up to date. The comparison is content-based rather than timestamp-
based.

The flow exports the project managed by this CLI. It does not guess or discover
unrelated Vivado projects elsewhere on the machine. `paths.build.root` is the
only configurable filesystem path. All generated paths are derived from it, so
a one-off external build root is selected with:

```bash
./gpgpu --set paths.build.root=/workspace/gpgpu-build run vivado:all
```

This places the managed project at
`/workspace/gpgpu-build/hardware/vivado/GPU/GPU.xpr`, software program outputs
under `/workspace/gpgpu-build/software/programs/<program>/`, RTL test outputs
under `/workspace/gpgpu-build/tests/rtl/`, and the doit database at
`/workspace/gpgpu-build/.doit.db`. Source paths such as `hardware/rtl`,
`hardware/constraints`, `software/programs`, and `tests/` are fixed parts of the
repository layout and are not independently configurable. Scripts can obtain
the normalized absolute root without parsing YAML:

```bash
./gpgpu config get paths.build.root --resolved-path
```

For safety, the resolved build root cannot be the repository root, one of its
ancestors, or overlap `config/`, `demo/`, `docs/`, `hardware/`, `software/`,
`tests/`, `tools/`, or `.git/`. This prevents clean operations and generated
files from modifying source or repository metadata.

Generated project state is written to `build/hardware/vivado/GPU/`. The final
outputs are:

```text
build/hardware/bitstream/gpgpu_block_design_wrapper.bit
build/hardware/platform/gpgpu_platform.xsa
```

Use `hardware.vivado.jobs` in a profile/local override, or a one-off CLI
override, to control Vivado parallelism:

```bash
./gpgpu --set hardware.vivado.jobs=8 run vivado:bitstream
```

All project, block-design, run, and output-product files under `build/` are
generated and may be deleted and recreated from the committed Tcl, RTL, and
XDC sources.