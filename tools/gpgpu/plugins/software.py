"""Build programs for the GPGPU and generate the host driver's headers."""
from gpgpu.api import Backends, Task, Toolchain


def tasks(backend: Backends) -> list[Task]:
    cc = backend(Toolchain)
    result = [
        Task("software:host:platform", "Regenerate the platform header of the driver from the RTL and the configuration.",
             cc.host_platform_header(), requires=("rtl:config",)),
        Task("software:programs:layout", "Write the linker layout (MEMORY regions) from architecture.memory and the RTL.",
             cc.linker_layout(), requires=("rtl:constants",)),
        Task("software:runtime:hw", "Write the header of the hardware the simulator models from the RTL constants.",
             cc.hardware_header(), requires=("rtl:constants",)),
        Task("software:runtime:check", "Run every RTL case on the C simulator and compare it with the Python model.",
             cc.runtime_check(), needs=("software:runtime:hw",), requires=("rtl:generate",)),
    ]
    for program in cc.programs():
        result += _program(cc, program, f"software:programs:{program}")
    return result


def _program(cc: Toolchain, program: str, prefix: str) -> list[Task]:
    """A program (docs/runtime-spec.md): kernels in <program>.c, the host program in host.c."""
    return [
        Task(f"{prefix}:clean", "Remove the build outputs of the program.", cc.clean(program)),
        Task(f"{prefix}:kernels", "Scan the kernels and generate their entry code and launch functions.",
             cc.generate_kernels(program)),
        Task(f"{prefix}:elf", "Compile and link the kernels (RISC-V).", cc.build_elf(program),
             needs=(f"{prefix}:kernels", "software:programs:layout")),
        Task(f"{prefix}:module", "Write the module: the kernels' code and data for the host program.",
             cc.build_module(program), needs=(f"{prefix}:elf",), requires=("rtl:constants",)),
        Task(f"{prefix}:dump", "Generate the complete RISC-V disassembly.", cc.disassemble(program), needs=(f"{prefix}:elf",)),
        Task(f"{prefix}:assembly", "Generate the cleaned RISC-V assembly listing.",
             cc.assembly(program), needs=(f"{prefix}:dump",)),
        Task(f"{prefix}:sim:build", "Build the host program for this PC, with the functional simulator.",
             cc.build_simulator_program(program), needs=(f"{prefix}:module", "software:runtime:hw")),
        Task(f"{prefix}:sim", "Build and run the program in the simulator (software.runtime.arguments).",
             cc.run_simulator_program(program), needs=(f"{prefix}:sim:build",)),
        Task(f"{prefix}:host", "Build the host program for the board's A9, against the platform's BSP.",
             cc.build_board_program(program), needs=(f"{prefix}:module", "software:host:platform"),
             requires=("vitis:build:platform",)),
        Task(f"{prefix}:all", "Build the kernels, their listing and the simulator program.",
             needs=(f"{prefix}:assembly", f"{prefix}:sim:build")),
    ]
