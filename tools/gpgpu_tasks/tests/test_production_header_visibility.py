"""Header visibility must survive independent compilation and IP packaging."""
from pathlib import Path
import re

from config import resolve_config
from tools.hardware.vivado.tasks import production_inputs

ROOT = Path(__file__).resolve().parents[3]


def test_every_production_macro_consumer_includes_its_header_explicitly():
    _, sources, headers = production_inputs(resolve_config(ROOT))
    macros = {macro: header.name for header in headers
              for macro in re.findall(r'^`define\s+(\w+)', header.read_text(), re.M)}
    missing = []
    for source_path in sources:
        if source_path in headers:
            continue
        source = source_path.read_text()
        for header in sorted({macros[m] for m in re.findall(r'`(\w+)', source) if m in macros}):
            if not re.search(r'^\s*`include\s+"' + re.escape(header) + '"', source, re.M):
                missing.append((source_path.name, header))
    assert not missing, f'Production files rely on global include/compile order: {missing}'
