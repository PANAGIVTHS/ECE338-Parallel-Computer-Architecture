"""Build the host software: editable project, software platform, host application and games."""
from gpgpu.api import Backends, GameFlow, PlatformFlow, Task


def tasks(backend: Backends) -> list[Task]:
    flow = backend(PlatformFlow)
    games = [
        Task(f"vitis:build:games:{game}", "Build the game's host application, after the platform.", flow.build_game(game),
             needs=("vitis:build:platform", "software:host:platform", f"software:games:{game}:fetch",
                    f"software:games:{game}:configure", f"software:games:{game}:assets", f"software:games:{game}:kernel"))
        for game in backend(GameFlow).games()]
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
        *games,
    ]
