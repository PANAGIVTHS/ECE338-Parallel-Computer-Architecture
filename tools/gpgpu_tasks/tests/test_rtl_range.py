"""Directed suite range selection; no vendor tools or shared build mutations."""
from pathlib import Path
import sys

import pytest
from config import resolve_config
from tools.tests import rtl

ROOT = Path(__file__).resolve().parents[3]


def test_inclusive_range_plusargs():
    assert rtl.rtl_range_plusargs("1-10") == ["+TEST_IDX=1", "+TEST_END=10"]


@pytest.mark.parametrize("value,expected", [
    ("all", []), ("5-5", ["+TEST_IDX=5", "+TEST_END=5"]),
    ("8-12", ["+TEST_IDX=8", "+TEST_END=12"]),
])
def test_range_boundaries(value, expected):
    assert rtl.rtl_range_plusargs(value) == expected


@pytest.mark.parametrize("value", ["", "0-3", "5-1", "1-", "-1-3", "all;run", "1-2-3", "1-2147483648"])
def test_invalid_range_is_rejected(value):
    with pytest.raises(ValueError, match="tests.rtl.range"):
        rtl.rtl_range_plusargs(value)


def configured_tasks(tmp_path, selection):
    config = resolve_config(ROOT, overrides=[
        f"paths.build.root={tmp_path / 'build'}", f"tests.rtl.range={selection}",
    ], allow_new_keys=False)
    return {task['name']: task for task in rtl.create_tasks(config)}


def test_range_reaches_smx_and_e2e_without_recompile(tmp_path):
    graph = configured_tasks(tmp_path, "8-12")
    everything = configured_tasks(tmp_path, "all")
    for suite in ('smx', 'e2e'):
        command = graph[f'tests:rtl:{suite}:run']['actions'][0][1][0]
        assert command[-2:] == ['+TEST_IDX=8', '+TEST_END=12']
        assert graph[f'tests:rtl:{suite}:build']['actions'] == everything[f'tests:rtl:{suite}:build']['actions']
    # Random testing has its own selection and must remain unchanged.
    assert graph['tests:rtl:random']['actions'] == configured_tasks(tmp_path, "all")['tests:rtl:random']['actions']


def test_shipped_profile_defaults_to_all():
    assert resolve_config(ROOT).get('tests.rtl.range') == 'all'


def test_run_rejects_missing_explicit_test_before_simulator(tmp_path):
    root = tmp_path / 'tests'
    (root / 'cases/test2').mkdir(parents=True)
    (root / 'cases/test2/program.asm').write_text('addi x1, x0, 1\n')
    with pytest.raises(ValueError, match='test3'):
        rtl.run_smx(['not-a-real-executable', '+TEST_IDX=2', '+TEST_END=3'], root, tmp_path / 'build/simulation.log')


def test_range_flags_reach_real_subprocess(tmp_path):
    root = tmp_path / 'tests'
    for n in (2, 3):
        p = root / f'cases/test{n}'
        p.mkdir(parents=True)
        (p / 'program.asm').write_text('addi x1, x0, 1\n')
    script = "import sys; assert sys.argv[1:] == ['+TEST_IDX=2', '+TEST_END=3']; print('[SUCCESS] range flags received')"
    log = tmp_path / 'build/simulation.log'
    rtl.run_smx([sys.executable, '-c', script, '+TEST_IDX=2', '+TEST_END=3'], root, log)
    assert '[SUCCESS] range flags received' in log.read_text()
