"""Test the RTL: directed suites on the simulator, the GPGPU model and random programs."""
from gpgpu.api import Backends, RtlFlow, Task

SUITES = {
    "smx": "the SMX-only suite, with direct memory access",
    "e2e": "the end-to-end suite, only through AXI4-Lite and the IRQ",
    "ddr": "the DDR suite, with kernels storing to the framebuffers",
}


def tasks(backend: Backends) -> list[Task]:
    rtl = backend(RtlFlow)
    result = [
        Task("rtl:identity", "Record the last commit and uncommitted changes of the RTL for BUILD_ID.", rtl.identity()),  # also vivado:_identity
        Task("rtl:constants", "Elaborate the RTL packages and write every constant for the GPGPU model.", rtl.constants()),
        Task("rtl:generate", "Assemble the cases and run them on the GPGPU model for the expected results.",
             rtl.generate(), needs=("rtl:constants",)),
        Task("rtl:random", "Generate and run reproducible random programs on the SMX bench.",
             rtl.random(), needs=("rtl:constants", "rtl:smx:build")),
        Task("rtl:build", "Build every suite.", needs=tuple(f"rtl:{suite}:build" for suite in sorted(SUITES))),
        Task("rtl:run", "Run every suite.", needs=tuple(f"rtl:{suite}:run" for suite in sorted(SUITES))),
        Task("rtl:all", "Generate, build and run every suite.", needs=("rtl:run",)),
    ]
    for suite, description in SUITES.items():
        result += [
            Task(f"rtl:{suite}:build", f"Build {description}.", rtl.build_suite(suite), needs=("rtl:identity",)),
            Task(f"rtl:{suite}:run", f"Run {description}.", rtl.run_suite(suite),
                 needs=("rtl:generate", f"rtl:{suite}:build")),
            Task(f"rtl:{suite}:all", f"Generate, build and run {description}.", needs=(f"rtl:{suite}:run",)),
        ]
    return result
