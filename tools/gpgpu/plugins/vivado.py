"""Build the hardware: packaged IP, system project, bitstream and hardware platform."""
from gpgpu.api import Backends, DesignProject, HardwareFlow, Task


def tasks(backend: Backends) -> list[Task]:
    flow = backend(HardwareFlow)
    return [
        Task("vivado:_identity", "Record the last commit and uncommitted changes of the RTL for BUILD_ID.", flow.identity()),
        Task("vivado:ip:create", "Recreate the IP development project from the production RTL.",
             flow.create_ip(), needs=("vivado:_identity",)),
        Task("vivado:ip:build", "Package and validate the IP, then publish its repository.",
             flow.package_ip(), needs=("vivado:ip:create", "vivado:_identity")),
        Task("vivado:system:create", "Create or update the system project, block design and wrapper.",
             flow.create_system(), needs=("vivado:ip:build",)),
        Task("vivado:system:synthesis", "Run synthesis on the system project.",
             flow.synthesize(), needs=("vivado:system:create",)),
        Task("vivado:system:implementation", "Run implementation on the synthesized design.",
             flow.implement(), needs=("vivado:system:synthesis",)),
        Task("vivado:system:bitstream", "Generate and publish the bitstream.",
             flow.bitstream(), needs=("vivado:system:implementation",)),
        Task("vivado:system:build", "Export the hardware platform, after everything before it.",
             flow.export_hardware(), needs=("vivado:system:bitstream",)),
    ]


def projects(backend: Backends) -> list[DesignProject]:
    return backend(HardwareFlow).projects()
