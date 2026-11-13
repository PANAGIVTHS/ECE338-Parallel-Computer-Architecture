"""Build the host software: editable project, software platform and host application."""
from gpgpu.api import Backends, PlatformFlow, Task


def tasks(backend: Backends) -> list[Task]:
    flow = backend(PlatformFlow)
    return [
        Task("vitis:project", "Create the editable project from the existing hardware platform.",
             flow.create_project(), requires=("vivado:system:build",)),
        Task("vitis:build:platform", "Build the software platform and verify its outputs.",
             flow.build_platform(), needs=("vitis:project",)),
        Task("vitis:build:host", "Build the host application after the platform.",
             flow.build_host(), needs=("vitis:build:platform", "software:host:platform", "software:host:autorun")),
        Task("vitis:build:all", "Build the software platform and the host application.",
             needs=("vitis:build:host",)),
        Task("vitis:export", "Replace the committed default project with a portable snapshot of the editable one.",
             flow.export_project()),
    ]
