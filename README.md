# ECE338-Parallel-Computer-Architecture

A small general-purpose GPU for FPGAs, written in SystemVerilog. Kernels are written
in C and built for RISC-V. All the lanes of the GPU run the same kernel in lockstep.
The design runs on a Zynq-7000 board, with a host program on its ARM processor and a
display over HDMI.

## Quick start

You need Python 3.11 or newer, Verilator, GNU make, a C++ compiler and a bare-metal
RISC-V GCC. [uv](https://docs.astral.sh/uv/) is optional.

```bash
./gpgpu doctor                        # check the tools on your machine
./gpgpu rtl smx:all                   # simulate the GPU on the test cases
./gpgpu software programs:simple:all  # build a kernel
./gpgpu <category> --help             # list the tasks of a category
```

The categories are `docs`, `fpga`, `rtl`, `software`, `vitis` and `vivado`. The first
run installs the Python dependencies in `.venv`.

## Documentation

The manual starts at [docs/manual/index.md](docs/manual/index.md). To read it as a web
site:

```bash
./gpgpu docs site:serve               # http://127.0.0.1:8000
```

Also in the repository:

- [The gpgpu command](tools/gpgpu/README.md): how it is built, and how to add a task
- [The programs](software/programs/README.md): how to write and build a kernel
- [The block design](hardware/bd/README.md): why it is the way it is
