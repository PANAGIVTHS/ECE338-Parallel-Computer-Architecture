from __future__ import annotations

import inspect
from pathlib import Path
import random

from tools.tests import random_tester


def test_random_program_generation_is_reproducible_from_global_seed(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.asm"
    second = tmp_path / "second.asm"
    different = tmp_path / "different.asm"

    random.seed(4242)
    random_tester.generate_random_assembly(first)
    random.seed(4242)
    random_tester.generate_random_assembly(second)
    random.seed(4243)
    random_tester.generate_random_assembly(different)

    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    assert first.read_text(encoding="utf-8") != different.read_text(encoding="utf-8")
    assert first.read_text(encoding="utf-8").endswith("jalr x0, 0(x1)\n")
