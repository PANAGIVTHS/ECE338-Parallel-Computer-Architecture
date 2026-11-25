"""Build the user manual, or serve it while writing it."""
from gpgpu.api import Backends, ManualSite, Task


def tasks(backend: Backends) -> list[Task]:
    manual = backend(ManualSite)
    return [
        Task("docs:site:build", "Build the manual's static site, rejecting broken links and images.", manual.build()),
        Task("docs:site:serve", "Serve the manual in the background, rebuilt on every edit.", manual.serve()),
        Task("docs:site:stop", "Stop serving the manual.", manual.stop()),
    ]
