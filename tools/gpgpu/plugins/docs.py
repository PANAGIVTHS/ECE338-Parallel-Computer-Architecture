"""Build the architecture map: the YAML model under docs/architecture-map and its zoomable viewer."""
from gpgpu.api import Backends, DocsFlow, Task


def tasks(backend: Backends) -> list[Task]:
    docs = backend(DocsFlow)
    return [
        Task("docs:map:validate", "Check the map's model: keys, kinds, wires and source paths.", docs.validate_map()),
        Task("docs:map:serve", "Serve the viewer on the live model until interrupted; reload the page after an edit.",
             docs.serve_map(), needs=("docs:map:validate",)),
        Task("docs:map:build", "Assemble the map as a static site under the build root.", docs.build_map(),
             needs=("docs:map:validate",)),
    ]
