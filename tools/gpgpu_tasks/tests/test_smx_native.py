"""Opt-in regression against an actually compiled native SMX bench."""
import os
import re
from pathlib import Path
import subprocess

import pytest


def test_native_bench_stops_without_reading_a_phantom_case():
    executable = os.environ.get("SMX_BINARY")
    if not executable:
        pytest.skip("set SMX_BINARY to run the compiled-bench regression")
    repo = Path(__file__).resolve().parents[3]
    test_root = Path(os.environ.get("SMX_TEST_ROOT", repo / "tests/hardware/rtl"))
    expected = sorted(int(p.parent.name[4:]) for p in (test_root / "cases").glob("test*/program.mem"))
    assert expected, "Generate cases first (or set SMX_TEST_ROOT to a generated-case build directory)"
    result = subprocess.run([executable], cwd=test_root, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(map(int, re.findall(r"\[SUCCESS\] Test (\d+) is correct", result.stdout))) == expected
    assert f"Starting test {expected[-1] + 1}" not in result.stdout
    assert "$readmem file not found" not in result.stdout
