from __future__ import annotations

import json
from pathlib import Path
import random
import sys

import pytest

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
    assert first.read_text(encoding="utf-8").endswith("addi x17, x0, 0\necall\n")


def configure_native_run(tmp_path, monkeypatch, *, output="[SUCCESS] native", status=0):
    simulator = tmp_path / "native smx"
    invocations = tmp_path / "invocations.jsonl"
    simulator.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        "case = pathlib.Path('cases/test999')\n"
        "assert (case / 'program.mem').is_file()\n"
        "assert (case / 'data.mem').is_file()\n"
        "assert (case / 'regfile_c1.mem').is_file()\n"
        f"with open({str(invocations)!r}, 'a') as log:\n"
        "    log.write(json.dumps({'args': sys.argv[1:], 'cwd': str(pathlib.Path.cwd()), "
        "'assembly': (case / 'program.asm').read_text()}) + '\\n')\n"
        f"print({output!r}, flush=True)\n"
        f"sys.exit({status})\n",
        encoding="utf-8",
    )
    simulator.chmod(0o755)
    log = tmp_path / "logs/random.log"
    monkeypatch.setattr(sys, "argv", [
        "random_tester.py", "--iterations", "2", "--seed", "4242",
        "--num-cores", "2", "--python", sys.executable,
        "--simulator", str(simulator), "--test-root", str(tmp_path), "--log", str(log),
    ])
    return invocations, log


def test_random_runner_invokes_native_executable_with_plusargs(tmp_path, monkeypatch):
    invocations, log = configure_native_run(tmp_path, monkeypatch)

    assert random_tester.main() == 0

    records = [json.loads(line) for line in invocations.read_text().splitlines()]
    assert len(records) == 2
    for record, seed in zip(records, (4242, 4243)):
        assert record['args'] == ['+TEST_IDX=999', '+TEST_END=999']
        assert record['cwd'] == str(tmp_path)
        expected = tmp_path / f"expected-{seed}.asm"
        random.seed(seed)
        random_tester.generate_random_assembly(expected)
        assert record['assembly'] == expected.read_text()
    output = log.read_text()
    assert "Base seed: 4242" in output
    assert "Iteration 2/2: Generating test with seed 4243" in output
    assert output.count("[SUCCESS] native") == 2
    assert "SUCCESS! All 2 random tests passed flawlessly." in output


def test_success_removes_owned_scratch_case(tmp_path, monkeypatch):
    configure_native_run(tmp_path, monkeypatch)
    assert random_tester.main() == 0
    assert not (tmp_path / 'cases/test999').exists()


@pytest.mark.parametrize('output,status', [
    ('[FAIL] mismatch', 0), ('[WARNING] suspicious\n[SUCCESS]', 0),
    ('[ERROR] broken\n[SUCCESS]', 0), ('no success marker', 0), ('[SUCCESS]', 7),
])
def test_failed_native_run_preserves_reproducer(tmp_path, monkeypatch, output, status):
    invocations, log = configure_native_run(tmp_path, monkeypatch, output=output, status=status)
    assert random_tester.main() == 1
    case = tmp_path / 'cases/test999'
    for name in ('program.asm', 'program.mem', 'data.mem', 'regfile_c0.mem', 'regfile_c1.mem'):
        assert (case / name).is_file()
    assert len(invocations.read_text().splitlines()) == 1
    assert output in log.read_text()
    assert 'ITERATION 1 FAILED' in log.read_text()
    assert 'failing test has been preserved' in log.read_text()


@pytest.mark.parametrize('symlink', [False, True])
def test_existing_case_is_not_overwritten_or_cleaned(tmp_path, monkeypatch, symlink):
    invocations, _ = configure_native_run(tmp_path, monkeypatch)
    case = tmp_path / 'cases/test999'
    case.parent.mkdir()
    original = tmp_path / 'original' if symlink else case
    original.mkdir()
    if symlink:
        case.symlink_to(original, target_is_directory=True)
    for name in ('program.asm', 'program.mem', 'regfile_c0.mem', 'notes.txt'):
        (original / name).write_text('user-owned')

    with pytest.raises(SystemExit) as error:
        random_tester.main()

    assert error.value.code == 2
    assert not invocations.exists()
    assert {path.name: path.read_text() for path in original.iterdir()} == {
        name: 'user-owned' for name in ('program.asm', 'program.mem', 'regfile_c0.mem', 'notes.txt')
    }


def test_success_preserves_unexpected_scratch_files(tmp_path, monkeypatch):
    configure_native_run(tmp_path, monkeypatch)
    simulator = tmp_path / 'native smx'
    simulator.write_text(simulator.read_text().replace(
        "sys.exit(0)", "(case / 'notes.txt').write_text('keep me')\nsys.exit(0)"
    ))
    assert random_tester.main() == 0
    case = tmp_path / 'cases/test999'
    assert (case / 'notes.txt').read_text() == 'keep me'
    assert not (case / 'program.asm').exists()
    assert not (case / 'program.mem').exists()


def test_generator_failure_preserves_assembly_and_logs(tmp_path, monkeypatch):
    invocations, log = configure_native_run(tmp_path, monkeypatch)
    # A real child process fails before assembly, without mocking generators.
    python_index = sys.argv.index('--python') + 1
    sys.argv[python_index] = '/bin/false'
    assert random_tester.main() == 1
    assert (tmp_path / 'cases/test999/program.asm').is_file()
    assert not invocations.exists()
    assert 'Command failed with status 1' in log.read_text()
    assert 'failing test has been preserved' in log.read_text()


@pytest.mark.parametrize('option,value', [
    ('--iterations', '0'), ('--num-cores', '0'), ('--vvp', 'vvp'),
])
def test_invalid_or_removed_options_are_rejected(tmp_path, monkeypatch, option, value):
    configure_native_run(tmp_path, monkeypatch)
    if option in sys.argv:
        sys.argv[sys.argv.index(option) + 1] = value
    else:
        sys.argv.extend([option, value])
    with pytest.raises(SystemExit) as error:
        random_tester.main()
    assert error.value.code == 2
    assert not (tmp_path / 'cases/test999').exists()
