"""Basic checks of the CLI's structure. Nothing here starts a vendor tool."""
import ast
import json
import re
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from gpgpu.adapters.doit_engine import _StateCheck
from gpgpu.adapters.tools import Machine
from gpgpu.adapters.vivado.system_project import canonicalize
from gpgpu.api import GpgpuError, Step, SyncRefused, SyncReport, SyncState, Task, classify
from gpgpu.app.registry import Registry
from gpgpu.app.workspace import Workspace
from gpgpu.bootstrap import REPO_ROOT, open_workspace

PACKAGE = REPO_ROOT / "tools/gpgpu"
# Each layer may import itself and these. Only bootstrap.py sees everything.
ALLOWED = {"api": {"api"}, "app": {"api", "app"}, "plugins": {"api"}, "adapters": {"api", "adapters"}, "cli": {"api", "bootstrap", "cli"}}
TOOLS = {"subprocess", "doit", "pyslang", "yaml", "pydantic"}


def imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            found.add(node.module or "")
        elif isinstance(node, ast.ImportFrom):
            found.add(f"gpgpu.{path.relative_to(PACKAGE).parts[0]}")  # a relative import stays in its layer
    return found


@pytest.mark.parametrize("layer", ALLOWED)
def test_layers_only_import_what_they_may(layer):
    for path in (PACKAGE / layer).rglob("*.py"):
        internal = {name.split(".")[1] for name in imports(path) if name.startswith("gpgpu.")}
        assert internal <= ALLOWED[layer], path


@pytest.mark.parametrize("layer", ["api", "app", "plugins"])
def test_only_adapters_touch_tools(layer):
    for path in (PACKAGE / layer).rglob("*.py"):
        assert not {name.split(".")[0] for name in imports(path)} & TOOLS, path


@pytest.mark.parametrize("layer", ["api", "app", "cli"])
def test_only_adapters_and_plugins_name_tools(layer):
    for path in (PACKAGE / layer).rglob("*.py"):
        assert not re.search(r"vivado|vitis|verilator|gcc|doit|\\bssh\\b", path.read_text(), re.I), path


def test_the_real_graph_loads_with_valid_categories():
    workspace = open_workspace()
    catalog = workspace._catalog
    assert not catalog.failures and not catalog.unavailable
    assert {"fpga", "rtl", "software", "vitis", "vivado"} <= {task.category for task in catalog.tasks.values()}
    assert {"vivado:ip:create", "rtl:identity", "fpga:programs:simple:all"} <= catalog.tasks.keys()
    assert workspace.projects() == ["ip", "system"]
    assert [task.command for task in workspace.tasks("vivado")] == [
        "ip:create", "ip:build", "system:create", "system:synthesis", "system:implementation", "system:bitstream", "system:build"]


def test_categories_stay_separate_except_for_quick_software_builds():
    workspace = open_workspace()
    for task in workspace._catalog.tasks.values():
        for need in (*task.needs, *task.setup):
            assert need.partition(":")[0] in (task.category, "software"), f"{task.name} would run {need}"
        for required in task.requires:
            assert workspace._catalog.tasks[required].step.outputs, f"{required} has nothing for {task.name} to check"


def test_every_input_another_task_produces_is_declared():
    """pydoit only knows a run's own tasks, so an undeclared producer would simply not run."""
    workspace = open_workspace()
    tasks = workspace._catalog.tasks
    producers: dict[Path, set[str]] = {}
    for task in tasks.values():
        for output in task.step.outputs:
            producers.setdefault(output, set()).add(task.name)
    for task in tasks.values():
        runs = workspace._closure(task.name)
        declared = {found.name for item in runs for name in (item.name, *item.requires) for found in workspace._closure(name)}
        for path in task.step.inputs:
            assert path not in producers or producers[path] & declared, f"{task.name} reads {path.name}"


def test_config_rejects_typos_and_names_the_source():
    with pytest.raises(GpgpuError, match="Unknown configuration option"):
        open_workspace(overrides=["no.such.key=1"])
    errors, _ = open_workspace(overrides=["hardware.vivado.jobs=0"]).validate()
    assert any("hardware.vivado.jobs" in error and "--set" in error for error in errors)


def test_sync_state_table():
    assert classify(False, False) is SyncState.IN_SYNC
    assert classify(True, False) is SyncState.PROJECT_AHEAD
    assert classify(False, True) is SyncState.SOURCE_AHEAD
    assert classify(True, True) is SyncState.DIVERGED


def test_canonicalize_sorts_only_net_pin_lists():
    text = "connect_bd_net -net n [get_bd_pins b/x] \\\n  [get_bd_pins a/y]\nset_property x y\n"
    assert canonicalize(text) == "connect_bd_net -net n [get_bd_pins a/y] \\\n[get_bd_pins b/x]\nset_property x y\n"


@pytest.mark.parametrize("value", [None, (1, 2), {"a": "b"}])
def test_state_probe_survives_the_database(value):
    check = _StateCheck(SimpleNamespace(key="k", state=lambda: value))
    assert check(None, {}) is False
    saved = SimpleNamespace(value_savers=[])
    check.configure_task(saved)
    assert check(None, json.loads(json.dumps(saved.value_savers[0]()))) is True


class FakeProject:
    name, create_task = "design", "good:create"
    blocked_by = frozenset({SyncState.SOURCE_AHEAD})
    state = SyncState.IN_SYNC

    def status(self):
        return SyncReport(self.name, self.state, source_changes=("design.tcl",))


class FakeEngine:
    def __init__(self, stale=()):
        self.ran = []
        self.loaded = []
        self.reasons = list(stale)

    def run(self, tasks, target, *, monitor):
        self.ran.append(target)
        self.loaded = sorted(task.name for task in tasks)
        return 0

    def stale(self, tasks):
        return self.reasons


def _workspace(plugins, engine=None):
    settings = SimpleNamespace(unknown_keys=list)
    environment = SimpleNamespace(checks=list, exclusive=lambda categories, command: nullcontext())
    return Workspace(settings, Registry(plugins), lambda port: None, engine or FakeEngine(), environment)


GOOD = SimpleNamespace(tasks=lambda backend: [Task("good:create", "Create.", Step(always_run=True)),
                                              Task("good:_stage", "Internal."), Task("good:all", "All.", needs=("good:create",))],
                       projects=lambda backend: [FakeProject()])


def _broken(backend):
    raise RuntimeError("no tool")


def test_one_plugin_failing_leaves_the_rest_usable():
    needs_broken = SimpleNamespace(tasks=lambda backend: [Task("down:x", "X.", needs=("bad:y",))])
    workspace = _workspace({"good": GOOD, "bad": SimpleNamespace(tasks=_broken), "down": needs_broken})
    assert [task.command for task in workspace.tasks("good")] == ["create", "all"]
    assert workspace.run("good:all") == 0
    with pytest.raises(GpgpuError, match="bad commands did not load: RuntimeError: no tool"):
        workspace.run("bad:y")
    with pytest.raises(GpgpuError, match="unavailable: it needs bad:y"):
        workspace.run("down:x")


def test_plugins_may_only_declare_their_own_category():
    workspace = _workspace({"other": GOOD})
    with pytest.raises(GpgpuError, match="may only declare other"):
        workspace.run("other:all")


def test_unknown_command_suggests_a_close_one():
    with pytest.raises(GpgpuError) as error:
        _workspace({"good": GOOD}).run("good:creat")
    assert "gpgpu good create" in error.value.hint


def test_required_tasks_are_checked_and_never_run(tmp_path):
    built = tmp_path / "platform.xsa"
    plugins = {"hw": SimpleNamespace(tasks=lambda backend: [Task("hw:build", "Build.", Step(always_run=True, outputs=(built,)))]),
               "sw": SimpleNamespace(tasks=lambda backend: [Task("sw:app", "App.", Step(always_run=True), requires=("hw:build",))])}
    engine = FakeEngine(stale=["rtl.sv changed"])
    workspace = _workspace(plugins, engine)
    with pytest.raises(GpgpuError, match="gpgpu sw app cannot start without platform.xsa") as error:
        workspace.run("sw:app")
    assert "`gpgpu hw build`" in error.value.hint and engine.ran == []
    built.touch()
    warnings = []
    assert workspace.run("sw:app", warn=warnings.append) == 0
    assert engine.loaded == ["sw:app"]  # the engine never even hears of hw:build
    assert "`gpgpu hw build` is out of date (rtl.sv changed)" in warnings[0]


def test_one_command_per_category_of_a_build_tree(tmp_path):
    machine = Machine(SimpleNamespace(build_root=tmp_path))
    with machine.exclusive({"a"}, "gpgpu a x"):
        with pytest.raises(GpgpuError, match="`gpgpu a x` .* is using the a tasks"):
            with machine.exclusive({"a", "b"}, "gpgpu a y"):
                pass
        with machine.exclusive({"b"}, "gpgpu b y"):  # another category is free, again
            pass
    with machine.exclusive({"a"}, "gpgpu a z"):  # released
        pass


@pytest.mark.parametrize("state,refused", [(SyncState.IN_SYNC, False), (SyncState.SOURCE_AHEAD, True)])
def test_build_refuses_to_ignore_edits_to_its_project(state, refused, monkeypatch):
    monkeypatch.setattr(FakeProject, "state", state)
    engine = FakeEngine()
    workspace = _workspace({"good": GOOD}, engine)
    if refused:
        with pytest.raises(SyncRefused, match="would ignore design.tcl"):
            workspace.run("good:all")
        assert engine.ran == []
    else:
        assert workspace.run("good:all") == 0
        assert engine.ran == ["good:all"]
