"""Build programs for the GPGPU and generate the host driver's headers."""
from gpgpu.api import Backends, Task, Toolchain


def tasks(backend: Backends) -> list[Task]:
    cc = backend(Toolchain)
    autorun = cc.autorun_program()
    result = [
        Task("software:host:platform", "Regenerate the platform header of the driver from the RTL and the configuration.",
             cc.host_platform_header(), requires=("rtl:config",)),
        Task("software:host:autorun", "Regenerate the header of the program the host runs from boot.",
             cc.host_autorun_header(),
             needs=(f"software:programs:{autorun}:mem", f"software:programs:{autorun}:image") if autorun else ()),
        Task("software:programs:layout", "Write the linker layout (MEMORY regions) from architecture.memory and the RTL.",
             cc.linker_layout(), requires=("rtl:constants",)),
    ]
    result += [
        Task("software:runtime:hw", "Write the header of the hardware the simulator models from the RTL constants.",
             cc.hardware_header(), requires=("rtl:constants",)),
        Task("software:runtime:check", "Run every RTL case on the C simulator and compare it with the Python model.",
             cc.runtime_check(), needs=("software:runtime:hw",), requires=("rtl:generate",)),
    ]
    runtime = set(cc.runtime_programs())
    for program in cc.programs():
        prefix = f"software:programs:{program}"
        if program in runtime:
            result += _runtime_program(cc, program, prefix)
            continue
        result += [
            Task(f"{prefix}:clean", "Remove the build outputs of the program.", cc.clean(program)),
            Task(f"{prefix}:x86:build", "Build the native x86 executable without running it.", cc.build_native(program)),
            Task(f"{prefix}:x86", "Build and run the native x86 executable.",
                 cc.run_native(program), needs=(f"{prefix}:x86:build",)),
            Task(f"{prefix}:elf", "Compile and link the RISC-V executable.", cc.build_elf(program),
                 needs=("software:programs:layout",)),
            Task(f"{prefix}:image", "Write the GMEM data image and the memory layout of the program.",
                 cc.program_image(program), needs=(f"{prefix}:elf",)),
            Task(f"{prefix}:dump", "Generate the complete RISC-V disassembly.",
                 cc.disassemble(program), needs=(f"{prefix}:elf",)),
            Task(f"{prefix}:assembly", "Generate the cleaned RISC-V assembly listing.",
                 cc.assembly(program), needs=(f"{prefix}:dump",)),
            Task(f"{prefix}:mem", "Generate the instruction-memory image.",
                 cc.memory_image(program), needs=(f"{prefix}:dump",)),
            Task(f"{prefix}:riscv:build", "Build the RISC-V program, its assembly and its data image.",
                 needs=(f"{prefix}:assembly", f"{prefix}:image")),
            Task(f"{prefix}:all", "Build both the native executable and the RISC-V program.",
                 needs=(f"{prefix}:riscv:build", f"{prefix}:x86:build")),
        ]
    return result


def _runtime_program(cc: Toolchain, program: str, prefix: str) -> list[Task]:
    """A program of the runtime: kernels in <program>.c, the host program in host.c."""
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
        Task(f"{prefix}:all", "Build the kernels, their listing and the simulator program.",
             needs=(f"{prefix}:assembly", f"{prefix}:sim:build")),
    ]
