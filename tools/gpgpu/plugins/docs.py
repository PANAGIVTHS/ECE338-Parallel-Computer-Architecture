"""Build the user manual, or serve it while writing it."""
from gpgpu.api import Backends, ManualSite, Task


def tasks(backend: Backends) -> list[Task]:
    manual = backend(ManualSite)
    return [
        Task("docs:site:build", "Build the manual's static site, rejecting broken links and images.", manual.build()),
        Task("docs:site:serve", "Serve the manual and rebuild it on every edit, until interrupted.", manual.serve()),
    ]
