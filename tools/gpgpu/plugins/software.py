"""Build programs for the GPGPU, the host driver's headers, and games with their PC simulation."""
from gpgpu.api import Backends, GameFlow, Task, Toolchain


def tasks(backend: Backends) -> list[Task]:
    cc = backend(Toolchain)
    autorun = cc.autorun_program()
    result = [
        Task("software:host:platform", "Regenerate the platform header of the driver from the RTL and the configuration.",
             cc.host_platform_header()),
        Task("software:host:autorun", "Regenerate the header of the program the host runs from boot.",
             cc.host_autorun_header(), needs=(f"software:programs:{autorun}:mem",) if autorun else ()),
    ]
    for program in cc.programs():
        prefix = f"software:programs:{program}"
        result += [
            Task(f"{prefix}:clean", "Remove the build outputs of the program.", cc.clean(program)),
            Task(f"{prefix}:x86:build", "Build the native x86 executable without running it.", cc.build_native(program)),
            Task(f"{prefix}:x86", "Build and run the native x86 executable.",
                 cc.run_native(program), needs=(f"{prefix}:x86:build",)),
            Task(f"{prefix}:elf", "Compile and link the RISC-V executable.", cc.build_elf(program)),
            Task(f"{prefix}:dump", "Generate the complete RISC-V disassembly.",
                 cc.disassemble(program), needs=(f"{prefix}:elf",)),
            Task(f"{prefix}:assembly", "Generate the cleaned RISC-V assembly listing.",
                 cc.assembly(program), needs=(f"{prefix}:dump",)),
            Task(f"{prefix}:mem", "Generate the instruction-memory image.",
                 cc.memory_image(program), needs=(f"{prefix}:dump",)),
            Task(f"{prefix}:riscv:build", "Build the RISC-V program and its assembly.", needs=(f"{prefix}:assembly",)),
            Task(f"{prefix}:all", "Build both the native executable and the RISC-V program.",
                 needs=(f"{prefix}:riscv:build", f"{prefix}:x86:build")),
        ]
    games = backend(GameFlow)
    for game in games.games():
        prefix, kernel = f"software:games:{game}", f"software:programs:{games.kernel(game)}"
        result += [
            Task(f"{prefix}:clean", "Remove everything built or fetched for the game.", games.clean(game)),
            Task(f"{prefix}:fetch", "Fetch the game's upstream source at the commit its manifest pins.", games.fetch(game)),
            Task(f"{prefix}:configure", "Generate the game's settings header from its manifest and the configuration.",
                 games.configure(game)),
            Task(f"{prefix}:assets", "Generate the file that links the game's data files into it.", games.assets(game)),
            Task(f"{prefix}:kernel", "Build the game's kernel and generate its IMEM image for the board build.",
                 games.kernel_image(game), needs=(f"{kernel}:riscv:build", f"{kernel}:mem")),
            Task(f"{prefix}:sim:build", "Build the game for this PC, with its kernel run natively on every lane.",
                 games.build_simulation(game),
                 needs=("software:host:platform", f"{prefix}:fetch", f"{prefix}:configure", f"{prefix}:assets")),
            Task(f"{prefix}:sim", "Run the game on this PC and write frames as pictures.",
                 games.run_simulation(game), needs=(f"{prefix}:sim:build",)),
            Task(f"{prefix}:verify", "Replay kernel runs captured from the simulation on the GPGPU model: "
                 "no divergence, no fault, the same picture.",
                 games.verify(game), needs=(f"{prefix}:sim:build", f"{kernel}:mem"), requires=("rtl:constants",)),
            Task(f"{prefix}:all", "Fetch, generate and build everything of the game that needs no board tools.",
                 needs=(f"{prefix}:kernel", f"{prefix}:sim:build")),
        ]
    return result
