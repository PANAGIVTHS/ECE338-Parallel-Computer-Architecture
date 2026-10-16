from __future__ import annotations

from pathlib import Path

from doit.cmd_base import TaskLoader2

from src import GPGPUTaskLoader, create_task_loader, run


class StubResolvedConfig:
    def __init__(self, repo_root: Path, build_path: Path) -> None:
        self.repo_root = repo_root
        self.build_path = build_path

    @property
    def build_root(self) -> Path:
        return self.build_path


def make_config(tmp_path: Path) -> StubResolvedConfig:
    task_module = tmp_path / "tools/software/programs.py"
    task_module.parent.mkdir(parents=True)
    task_module.write_text("def create_tasks(config):\n    return []\n", encoding="utf-8")
    rtl_module = tmp_path / "tools/tests/rtl.py"
    rtl_module.parent.mkdir(parents=True)
    rtl_module.write_text(
        "def create_tasks(config):\n"
        "    return [{'name': 'tests:rtl:all', 'actions': None}]\n",
        encoding="utf-8",
    )
    vivado_module = tmp_path / "tools/hardware/vivado/tasks.py"
    vivado_module.parent.mkdir(parents=True)
    vivado_module.write_text(
        "def create_tasks(config):\n"
        "    return [{'name': 'vivado:project', 'actions': None}]\n",
        encoding="utf-8",
    )
    vitis_module = tmp_path / "tools/hardware/vitis/tasks.py"
    vitis_module.parent.mkdir(parents=True)
    vitis_module.write_text(
        "def create_tasks(config):\n"
        "    return [{'name': 'vitis:project', 'actions': None}]\n",
        encoding="utf-8",
    )
    fpga_module = tmp_path / "tools/hardware/fpga/tasks.py"
    fpga_module.parent.mkdir(parents=True)
    fpga_module.write_text("def create_tasks(config):\n    return []\n", encoding="utf-8")
    return StubResolvedConfig(tmp_path, tmp_path / "build")


def test_loader_stores_resolved_config_and_configures_dep_file(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    loader = create_task_loader(config)  # type: ignore[arg-type]

    assert isinstance(loader, TaskLoader2)
    assert isinstance(loader, GPGPUTaskLoader)
    assert loader.API == 2
    assert loader.resolved_config is config
    assert loader.load_doit_config() == {
        "dep_file": str(tmp_path / "build/.doit.db"),
        "backend": "sqlite3",
    }
    assert (tmp_path / "build").is_dir()
    assert [task.name for task in loader.load_tasks(cmd=None, pos_args=[])] == [
        "tests:rtl:all",
        "vivado:project",
        "vitis:project",
    ]


def test_empty_task_project_can_be_executed_programmatically(tmp_path: Path) -> None:
    build_path = tmp_path / "build"
    build_path.mkdir()
    config = make_config(tmp_path)

    assert run(config, ["list"]) == 0  # type: ignore[arg-type]


def test_real_task_graph_loads_without_repository_on_python_path(tmp_path: Path) -> None:
    """Console scripts must not depend on pytest/cwd exposing the tools namespace."""
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[3]
    script = """
import importlib.util
import sys
from pathlib import Path
from config import resolve_config
from src import create_task_loader

assert importlib.util.find_spec('tools') is None
config = resolve_config(Path(sys.argv[1]))
tasks = create_task_loader(config).load_tasks(cmd=None, pos_args=[])
names = {task.name for task in tasks}
assert {'vivado:ip:create', 'vivado:system:build', 'vitis:build:all'} <= names
print('Task graph loaded without repository on sys.path')
"""
    result = subprocess.run(
        [sys.executable, '-I', '-c', script, str(repo)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Task graph loaded without repository on sys.path' in result.stdout
