from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import pytest

from tools.hardware.vivado import tasks as vivado


class StubResolvedConfig:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def get(self, key: str):
        values = {
            "architecture.num_cores": 8,
            "hardware.fpga.part": "xc7z020clg484-1",
            "hardware.vivado.project_name": "GPU",
            "hardware.vivado.bd_name": "gpgpu_block_design",
            "hardware.vivado.top": "gpgpu_block_design_wrapper",
            "hardware.vivado.xsa_name": "gpgpu_platform",
            "hardware.vivado.jobs": 8,
            "hardware.vivado.host_interface.address_gpio": "0x41200000",
            "hardware.vivado.host_interface.cmd_gpio": "0x41210000",
            "hardware.vivado.host_interface.rdata_gpio": "0x41220000",
            "hardware.vivado.host_interface.status_gpio": "0x41230000",
            "hardware.vivado.host_interface.wdata_gpio": "0x41240000",
            "tools.vivado.command": "vivado-configured",
        }
        return values[key]

    @property
    def build_root(self) -> Path:
        return self.repo_root / "build"


def make_repo(tmp_path: Path) -> StubResolvedConfig:
    for relative in (
        "hardware/rtl/constants.vh",
        "hardware/rtl/GPGPU.v",
        "hardware/rtl/Top.sv",
        "hardware/rtl/memory/Memory.v",
        "hardware/rtl/sp/Processor.sv",
        "hardware/constraints/smart_zynq.xdc",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// source\n", encoding="utf-8")

    scripts = tmp_path / "tools/hardware/vivado"
    scripts.mkdir(parents=True)
    for name in (
        "common.tcl",
        "create_project.tcl",
        "create_block_design.tcl",
        "export_block_design.tcl",
        "build_block_design.tcl",
        "generate_block_design_wrapper.tcl",
        "synthesis.tcl",
        "implementation.tcl",
        "bitstream.tcl",
        "export_hardware.tcl",
    ):
        (scripts / name).write_text("# Tcl\n", encoding="utf-8")
    return StubResolvedConfig(tmp_path)


def tasks_by_name(config: StubResolvedConfig) -> dict[str, dict]:
    return {task["name"]: task for task in vivado.create_tasks(config)}  # type: ignore[arg-type]


def test_vivado_tasks_form_a_strict_stage_pipeline(tmp_path: Path) -> None:
    tasks = tasks_by_name(make_repo(tmp_path))

    assert list(tasks) == [
        "vivado:project",
        "vivado:block-design:build",
        "vivado:block-design:run",
        "vivado:synthesis",
        "vivado:implementation",
        "vivado:bitstream",
        "vivado:xsa",
        "vivado:all",
    ]
    assert tasks["vivado:project"].get("task_dep", []) == []
    assert tasks["vivado:block-design:build"]["task_dep"] == ["vivado:project"]
    assert tasks["vivado:block-design:build"]["uptodate"] == [False]
    assert tasks["vivado:block-design:run"]["task_dep"] == ["vivado:block-design:build"]
    assert tasks["vivado:synthesis"]["task_dep"] == ["vivado:block-design:run"]
    assert tasks["vivado:implementation"]["task_dep"] == ["vivado:synthesis"]
    assert tasks["vivado:bitstream"]["task_dep"] == ["vivado:implementation"]
    assert tasks["vivado:xsa"]["task_dep"] == ["vivado:bitstream"]
    assert tasks["vivado:all"]["task_dep"] == ["vivado:xsa"]


def test_vivado_commands_use_configured_tool_and_portable_repository_paths(
    tmp_path: Path,
) -> None:
    config = make_repo(tmp_path)
    tasks = tasks_by_name(config)

    expected_scripts = {
        "vivado:project": "create_project.tcl",
        "vivado:block-design:build": "build_block_design.tcl",
        "vivado:block-design:run": "generate_block_design_wrapper.tcl",
        "vivado:synthesis": "synthesis.tcl",
        "vivado:implementation": "implementation.tcl",
        "vivado:bitstream": "bitstream.tcl",
        "vivado:xsa": "export_hardware.tcl",
    }
    for task_name, script_name in expected_scripts.items():
        command = tasks[task_name]["actions"][0][1][0]
        assert command[:4] == [
            "vivado-configured",
            "-mode",
            "batch",
            "-source",
        ]
        assert command[4] == str(tmp_path / f"tools/hardware/vivado/{script_name}")
        assert command[5] == "-tclargs"
        assert "-project-dir" in command
        assert str(tmp_path / "build/hardware/vivado/GPU") in command
        assert "-rtl-dir" in command
        assert str(tmp_path / "hardware/rtl") in command
        assert "-xdc-file" in command
        assert str(tmp_path / "hardware/constraints/smart_zynq.xdc") in command
        assert "-jobs" in command
        assert "8" in command
        assert command[command.index("-num-cores") + 1] == "8"
        assert command[command.index("-host-address-gpio") + 1] == "0x41200000"
        assert command[command.index("-host-cmd-gpio") + 1] == "0x41210000"
        assert command[command.index("-host-rdata-gpio") + 1] == "0x41220000"
        assert command[command.index("-host-status-gpio") + 1] == "0x41230000"
        assert command[command.index("-host-wdata-gpio") + 1] == "0x41240000"

    project_deps = set(tasks["vivado:project"]["file_dep"])
    assert str(tmp_path / "hardware/rtl/Top.sv") in project_deps
    assert str(tmp_path / "hardware/rtl/sp/Processor.sv") in project_deps
    assert str(tmp_path / "hardware/constraints/smart_zynq.xdc") in project_deps


def test_vivado_tasks_publish_expected_stage_artifacts(tmp_path: Path) -> None:
    tasks = tasks_by_name(make_repo(tmp_path))
    project = tmp_path / "build/hardware/vivado/GPU"

    assert tasks["vivado:project"]["targets"] == [str(project / "GPU.xpr")]
    assert tasks["vivado:block-design:build"]["targets"] == [
        str(project / "GPU.srcs/sources_1/bd/gpgpu_block_design/gpgpu_block_design.bd"),
    ]
    assert tasks["vivado:block-design:run"]["targets"] == [
        str(
            project
            / "GPU.gen/sources_1/bd/gpgpu_block_design/hdl/gpgpu_block_design_wrapper.v"
        ),
    ]
    assert tasks["vivado:synthesis"]["targets"] == [
        str(project / "GPU.runs/synth_1/gpgpu_block_design_wrapper.dcp")
    ]
    assert (
        str(
            project
            / "GPU.gen/sources_1/bd/gpgpu_block_design/hdl/gpgpu_block_design_wrapper.v"
        )
        in tasks["vivado:synthesis"]["file_dep"]
    )
    assert tasks["vivado:implementation"]["targets"] == [
        str(project / "GPU.runs/impl_1/gpgpu_block_design_wrapper_routed.dcp")
    ]
    assert (
        str(project / "GPU.runs/synth_1/gpgpu_block_design_wrapper.dcp")
        in tasks["vivado:implementation"]["file_dep"]
    )
    assert tasks["vivado:bitstream"]["targets"] == [
        str(tmp_path / "build/hardware/bitstream/gpgpu_block_design_wrapper.bit")
    ]
    assert (
        str(project / "GPU.runs/impl_1/gpgpu_block_design_wrapper_routed.dcp")
        in tasks["vivado:bitstream"]["file_dep"]
    )
    assert tasks["vivado:xsa"]["targets"] == [
        str(tmp_path / "build/hardware/platform/gpgpu_platform.xsa")
    ]
    assert (
        str(tmp_path / "build/hardware/bitstream/gpgpu_block_design_wrapper.bit")
        in tasks["vivado:xsa"]["file_dep"]
    )


def invoke(task: dict) -> None:
    for function, arguments in task["actions"]:
        function(*arguments)


def valid_raw_export() -> str:
    return (
        "# CHANGE DESIGN NAME HERE\nvariable design_name\n"
        "set design_name gpgpu_block_design\n"
        "set GPGPU_0 [create_bd_cell -type module -reference GPGPU GPGPU_0]\n"
    )


@pytest.mark.parametrize("warm", [False, True])
def test_bd_build_bootstraps_or_preserves_and_exports(tmp_path, monkeypatch, warm):
    tasks = tasks_by_name(make_repo(tmp_path))
    task = tasks["vivado:block-design:build"]
    bd = Path(task["targets"][0])
    template = tmp_path / "tools/hardware/vivado/create_block_design.tcl"
    if warm:
        bd.parent.mkdir(parents=True)
        bd.write_text("saved GUI edits")
    calls = []

    def vendor(command, **kwargs):
        stage = Path(command[4]).name
        calls.append(stage)
        if stage == "build_block_design.tcl":
            if not bd.exists():
                bd.parent.mkdir(parents=True)
                bd.write_text("bootstrap")
        elif stage == "export_block_design.tcl":
            raw = Path(command[command.index("-export-file") + 1])
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text(valid_raw_export())

    monkeypatch.setattr(vivado.subprocess, "run", vendor)
    invoke(task)
    assert calls == ["build_block_design.tcl", "export_block_design.tcl"]
    assert bd.read_text() == ("saved GUI edits" if warm else "bootstrap")
    assert "set design_name $::BD_NAME" in template.read_text()
    before = template.stat().st_mtime_ns
    invoke(task)
    assert template.stat().st_mtime_ns == before
    assert str(template) not in task["targets"]


@pytest.mark.parametrize("export_fails", [False, True])
def test_project_preserves_gui_before_destructive_recreation(
    tmp_path, monkeypatch, export_fails
):
    tasks = tasks_by_name(make_repo(tmp_path))
    project = Path(tasks["vivado:project"]["targets"][0])
    bd = Path(tasks["vivado:block-design:build"]["targets"][0])
    bd.parent.mkdir(parents=True)
    bd.write_text("valuable GUI edits")
    project.write_text("project")
    calls = []

    def vendor(command, **kwargs):
        stage = Path(command[4]).name
        calls.append(stage)
        if stage == "export_block_design.tcl":
            assert bd.read_text() == "valuable GUI edits"
            if export_fails:
                raise RuntimeError("export failed")
            raw = Path(command[command.index("-export-file") + 1])
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text(valid_raw_export())
        else:
            assert not bd.exists()
            project.parent.mkdir(parents=True, exist_ok=True)
            project.write_text("new project")

    monkeypatch.setattr(vivado.subprocess, "run", vendor)
    if export_fails:
        with pytest.raises(RuntimeError, match="export failed"):
            invoke(tasks["vivado:project"])
        assert bd.read_text() == "valuable GUI edits"
        assert project.read_text() == "project"
    else:
        invoke(tasks["vivado:project"])
        assert calls == ["export_block_design.tcl", "create_project.tcl"]
    assert str(bd) not in tasks["vivado:project"]["file_dep"]


def test_saved_bd_edits_are_direct_synthesis_and_xsa_inputs(tmp_path):
    tasks = tasks_by_name(make_repo(tmp_path))
    bd = tasks["vivado:block-design:build"]["targets"][0]
    assert bd in tasks["vivado:synthesis"]["file_dep"]
    assert bd in tasks["vivado:xsa"]["file_dep"]
    assert (
        str(tmp_path / "hardware/rtl/GPGPU.v") in tasks["vivado:synthesis"]["file_dep"]
    )
    assert (
        str(tmp_path / "hardware/constraints/smart_zynq.xdc")
        in tasks["vivado:synthesis"]["file_dep"]
    )


def test_committed_tcl_sources_are_checkout_portable() -> None:
    script_root = Path(__file__).resolve().parents[3] / "tools/hardware/vivado"

    for script in script_root.glob("*.tcl"):
        text = script.read_text(encoding="utf-8")
        assert "/home/" not in text
        assert "/workspace/" not in text
        assert "tsiantos" not in text.lower()


def test_tcl_scripts_keep_each_vivado_stage_separate() -> None:
    script_root = Path(__file__).resolve().parents[3] / "tools/hardware/vivado"
    project = (script_root / "create_project.tcl").read_text(encoding="utf-8")
    block_design = (script_root / "build_block_design.tcl").read_text(encoding="utf-8")
    wrapper = (script_root / "generate_block_design_wrapper.tcl").read_text(
        encoding="utf-8"
    )
    configuration = (script_root / "configure_block_design.tcl").read_text(
        encoding="utf-8"
    )
    synthesis = (script_root / "synthesis.tcl").read_text(encoding="utf-8")
    implementation = (script_root / "implementation.tcl").read_text(encoding="utf-8")
    bitstream = (script_root / "bitstream.tcl").read_text(encoding="utf-8")
    xsa = (script_root / "export_hardware.tcl").read_text(encoding="utf-8")

    assert 'glob -nocomplain [file join $source_dir "*.sv"]' in project
    assert "add_files -norecurse $rtl_files" in project
    assert "add_files -fileset constrs_1 -norecurse $XDC_FILE" in project
    assert "create_bd_design" not in project

    assert 'source [file join $SCRIPT_DIR "create_block_design.tcl"]' in block_design
    assert "open_bd_design $bd_file" in block_design
    for text in (block_design, wrapper):
        assert "remove_files" not in text
        assert "file delete" not in text
    assert "generate_target all $bd_file" in wrapper
    assert "make_wrapper -files $bd_file -top" in wrapper
    assert "set_property top $TOP_NAME" in wrapper
    assert "CONFIG.SP_PER_SM $NUM_CORES" in configuration
    assert "assign_bd_address -offset $offset" in configuration
    for variable in (
        "HOST_ADDRESS_GPIO",
        "HOST_CMD_GPIO",
        "HOST_RDATA_GPIO",
        "HOST_STATUS_GPIO",
        "HOST_WDATA_GPIO",
    ):
        assert variable in configuration
    assert "launch_runs synth_1" not in block_design

    assert "reset_run synth_1" in synthesis
    assert "launch_runs synth_1 -jobs $JOBS" in synthesis
    assert "launch_runs impl_1" not in synthesis

    assert "reset_run impl_1" in implementation
    assert "launch_runs impl_1 -to_step route_design -jobs $JOBS" in implementation
    assert "write_bitstream" not in implementation

    assert "launch_runs impl_1 -to_step write_bitstream -jobs $JOBS" in bitstream
    assert "reset_run impl_1 -from_step write_bitstream" in bitstream
    assert "file copy -force $generated_bitstream $output_bitstream" in bitstream
    assert "write_hw_platform -fixed -include_bit -force" in xsa
    assert "write_bitstream" not in xsa


def test_block_design_matches_documented_board_configuration() -> None:
    script_root = Path(__file__).resolve().parents[3] / "tools/hardware/vivado"
    repo_root = script_root.parents[2]
    block_design = (script_root / "create_block_design.tcl").read_text(encoding="utf-8")
    constraints = (repo_root / "hardware/constraints/smart_zynq.xdc").read_text(
        encoding="utf-8"
    )

    assert "CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {38}" in block_design
    assert "CONFIG.PCW_CLK0_FREQ {38095242}" in block_design
    assert "CONFIG.PCW_UIPARAM_DDR_PARTNO {MT41K256M16 RE-125}" in block_design
    assert "CONFIG.PCW_UIPARAM_DDR_BUS_WIDTH {16 Bit}" in block_design
    assert "CONFIG.PCW_EN_EMIO_UART0 {1}" in block_design
    assert "CONFIG.PCW_EN_UART0 {1}" in block_design
    assert "CONFIG.PCW_UART0_UART0_IO {EMIO}" in block_design
    assert (
        "create_bd_intf_port -mode Master -vlnv xilinx.com:interface:uart_rtl:1.0 UART_0_0"
        in block_design
    )
    assert "processing_system7_0/UART_0" in block_design
    assert "PACKAGE_PIN M17 [get_ports UART_0_0_rxd]" in constraints
    assert "PACKAGE_PIN L17 [get_ports UART_0_0_txd]" in constraints
    assert (
        "{PACKAGE_PIN P20 IOSTANDARD LVCMOS33} [get_ports o_idle_0]" in constraints
    )
    assert (
        "{PACKAGE_PIN P21 IOSTANDARD LVCMOS33} [get_ports o_running_0]" in constraints
    )
    assert "create_bd_port -dir O o_running_0" in block_design
    assert "get_ports o_running_0" in constraints


def test_committed_block_design_substitutes_configured_core_count() -> None:
    import tkinter

    source = (
        Path(__file__).resolve().parents[3]
        / "tools/hardware/vivado/create_block_design.tcl"
    ).read_text(encoding="utf-8")
    command = next(
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith("set_property CONFIG.SP_PER_SM ")
    )
    interpreter = tkinter.Tcl()
    interpreter.eval("set ::NUM_CORES 24; set GPGPU_0 /GPGPU_0")
    interpreter.eval("proc set_property {args} {set ::captured $args}")
    interpreter.eval(command)
    assert interpreter.splitlist(interpreter.eval("set ::captured")) == (
        "CONFIG.SP_PER_SM",
        "24",
        "/GPGPU_0",
    )


@pytest.mark.parametrize(
    "property_command",
    [
        "set_property -dict [list CONFIG.SP_PER_SM {8}] $GPGPU_0",
        "set_property CONFIG.SP_PER_SM {8} $GPGPU_0",
    ],
)
def test_normalize_exported_tcl_adds_portable_design_name_hook(
    tmp_path: Path, property_command: str
) -> None:
    raw = """# CHANGE DESIGN NAME HERE
variable design_name
set design_name gpgpu_block_design

set_property -dict [list CONFIG.SP_PER_SM {8}] $GPGPU_0
assign_bd_address -offset 0x41200000 -range 0x00010000 -target_address_space [get_bd_addr_spaces processing_system7_0/Data] [get_bd_addr_segs axi_gpio_address/S_AXI/Reg] -force
assign_bd_address -offset 0x41210000 -range 0x00010000 -target_address_space [get_bd_addr_spaces processing_system7_0/Data] [get_bd_addr_segs axi_gpio_cmd/S_AXI/Reg] -force
assign_bd_address -offset 0x41220000 -range 0x00010000 -target_address_space [get_bd_addr_spaces processing_system7_0/Data] [get_bd_addr_segs axi_gpio_rdata/S_AXI/Reg] -force
assign_bd_address -offset 0x41230000 -range 0x00010000 -target_address_space [get_bd_addr_spaces processing_system7_0/Data] [get_bd_addr_segs axi_gpio_status/S_AXI/Reg] -force
assign_bd_address -offset 0x41240000 -range 0x00010000 -target_address_space [get_bd_addr_spaces processing_system7_0/Data] [get_bd_addr_segs axi_gpio_wdata/S_AXI/Reg] -force
create_root_design ""
"""

    raw = raw.replace(
        "set_property -dict [list CONFIG.SP_PER_SM {8}] $GPGPU_0",
        property_command,
    )
    normalized = vivado.normalize_exported_tcl(raw, tmp_path, "gpgpu_block_design")

    assert "set design_name $::BD_NAME" in normalized
    assert "set design_name gpgpu_block_design" in normalized
    assert "CONFIG.SP_PER_SM $::NUM_CORES" in normalized

    # Execute the normalized property command through Tcl, not a string-only
    # assertion: braces previously passed the literal '$::NUM_CORES' to Vivado.
    import tkinter

    interpreter = tkinter.Tcl()
    interpreter.eval("set ::NUM_CORES 24; set GPGPU_0 /GPGPU_0")
    interpreter.eval("proc set_property {args} {set ::captured $args}")
    property_command = next(
        line for line in normalized.splitlines() if line.startswith("set_property ")
    )
    interpreter.eval(property_command)
    captured = interpreter.splitlist(interpreter.eval("set ::captured"))
    if captured[0] == "-dict":
        assert interpreter.splitlist(captured[1]) == ("CONFIG.SP_PER_SM", "24")
    else:
        assert captured == ("CONFIG.SP_PER_SM", "24", "/GPGPU_0")
    assert "-offset $::HOST_ADDRESS_GPIO" in normalized
    assert "-offset $::HOST_CMD_GPIO" in normalized
    assert "-offset $::HOST_RDATA_GPIO" in normalized
    assert "-offset $::HOST_STATUS_GPIO" in normalized
    assert "-offset $::HOST_WDATA_GPIO" in normalized
    assert "# CHANGE DESIGN NAME HERE" not in normalized
    assert all(line == line.rstrip() for line in normalized.splitlines())
    assert normalized.endswith("\n")
    assert not normalized.endswith("\n\n")


@pytest.mark.parametrize(
    "value",
    ["41200000", "0xnothex", "0x41200001", "0x100000000", 0x41200000],
)
def test_host_interface_address_validation_rejects_invalid_values(
    value: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        vivado._host_address(value, "hardware.vivado.host_interface.address_gpio")


def test_host_interface_addresses_must_be_unique(tmp_path: Path) -> None:
    class DuplicateAddressConfig(StubResolvedConfig):
        def get(self, key: str):
            if key == "hardware.vivado.host_interface.status_gpio":
                return "0x41220000"
            return super().get(key)

    with pytest.raises(ValueError, match="must be unique"):
        vivado.create_tasks(DuplicateAddressConfig(tmp_path))


def test_automatic_extract_skips_cleanly_on_first_clone(tmp_path: Path) -> None:
    terminal = StringIO()
    committed = tmp_path / "tools/hardware/vivado/create_block_design.tcl"
    committed.parent.mkdir(parents=True)
    committed.write_text("# committed bootstrap\n", encoding="utf-8")
    vivado._preserve_block_design_if_present(
        ["vivado-must-not-run"],
        tmp_path,
        tmp_path / "build/GPU/GPU.xpr",
        tmp_path
        / "build/GPU/GPU.srcs/sources_1/bd/gpgpu_block_design/gpgpu_block_design.bd",
        tmp_path / "build/GPU/.gpgpu/gpgpu_block_design.raw.tcl",
        committed,
        tmp_path,
        "gpgpu_block_design",
        terminal=terminal,
    )

    assert "bootstrap" in terminal.getvalue().lower()


def test_automatic_extract_updates_tcl_when_expected_project_bd_exists(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "build/GPU/GPU.xpr"
    bd_file = (
        tmp_path
        / "build/GPU/GPU.srcs/sources_1/bd/gpgpu_block_design/gpgpu_block_design.bd"
    )
    raw_export = tmp_path / "build/GPU/.gpgpu/gpgpu_block_design.raw.tcl"
    committed = tmp_path / "tools/hardware/vivado/create_block_design.tcl"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("project\n", encoding="utf-8")
    bd_file.parent.mkdir(parents=True)
    bd_file.write_text("design\n", encoding="utf-8")
    raw_text = (
        "# CHANGE DESIGN NAME HERE\n"
        "variable design_name\n"
        "set design_name gpgpu_block_design\n"
        "set GPGPU_0 [create_bd_cell -type module -reference GPGPU GPGPU_0]\n"
        'create_root_design ""\n'
    )
    command = [
        sys.executable,
        "-c",
        (
            f"from pathlib import Path; Path(r'{raw_export}').parent.mkdir(parents=True, exist_ok=True); "
            f"Path(r'{raw_export}').write_text({raw_text!r}, encoding='utf-8')"
        ),
    ]

    vivado._preserve_block_design_if_present(
        command,
        tmp_path,
        project_file,
        bd_file,
        raw_export,
        committed,
        tmp_path,
        "gpgpu_block_design",
    )

    assert committed.is_file()
    assert "set design_name $::BD_NAME" in committed.read_text(encoding="utf-8")


def test_automatic_extract_refuses_to_delete_differently_named_project_bd(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "build/GPU/GPU.xpr"
    expected_bd = (
        tmp_path
        / "build/GPU/GPU.srcs/sources_1/bd/gpgpu_block_design/gpgpu_block_design.bd"
    )
    old_bd = tmp_path / "build/GPU/GPU.srcs/sources_1/bd/design_1/design_1.bd"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("project\n", encoding="utf-8")
    old_bd.parent.mkdir(parents=True)
    old_bd.write_text("old design\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="design_1.bd"):
        vivado._preserve_block_design_if_present(
            ["vivado-must-not-run"],
            tmp_path,
            project_file,
            expected_bd,
            tmp_path / "build/GPU/.gpgpu/gpgpu_block_design.raw.tcl",
            tmp_path / "tools/hardware/vivado/create_block_design.tcl",
            tmp_path,
            "gpgpu_block_design",
        )


def test_export_warns_and_updates_when_committed_tcl_is_stale(tmp_path: Path) -> None:
    raw_export = tmp_path / "build/gpgpu_block_design.raw.tcl"
    committed = tmp_path / "tools/hardware/vivado/create_block_design.tcl"
    committed.parent.mkdir(parents=True)
    committed.write_text("# stale\n", encoding="utf-8")
    raw_text = (
        "# CHANGE DESIGN NAME HERE\n"
        "variable design_name\n"
        "set design_name gpgpu_block_design\n"
        "set GPGPU_0 [create_bd_cell -type module -reference GPGPU GPGPU_0]\n"
        'create_root_design ""\n'
    )
    command = [
        sys.executable,
        "-c",
        (
            f"from pathlib import Path; Path(r'{raw_export}').parent.mkdir(parents=True, exist_ok=True); "
            f"Path(r'{raw_export}').write_text({raw_text!r}, encoding='utf-8')"
        ),
    ]
    terminal = StringIO()

    vivado.export_block_design(
        command,
        tmp_path,
        raw_export,
        committed,
        tmp_path,
        "gpgpu_block_design",
        terminal=terminal,
    )

    assert "WARNING" in terminal.getvalue()
    assert "out of date" in terminal.getvalue()
    assert "set design_name $::BD_NAME" in committed.read_text(encoding="utf-8")
    assert not raw_export.exists()


def test_export_reports_up_to_date_without_warning(tmp_path: Path) -> None:
    raw_export = tmp_path / "build/gpgpu_block_design.raw.tcl"
    committed = tmp_path / "tools/hardware/vivado/create_block_design.tcl"
    committed.parent.mkdir(parents=True)
    raw_text = (
        "# CHANGE DESIGN NAME HERE\n"
        "variable design_name\n"
        "set design_name gpgpu_block_design\n"
        "set GPGPU_0 [create_bd_cell -type module -reference GPGPU GPGPU_0]\n"
        'create_root_design ""\n'
    )
    committed.write_text(
        vivado.normalize_exported_tcl(raw_text, tmp_path, "gpgpu_block_design"),
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "-c",
        (
            f"from pathlib import Path; Path(r'{raw_export}').parent.mkdir(parents=True, exist_ok=True); "
            f"Path(r'{raw_export}').write_text({raw_text!r}, encoding='utf-8')"
        ),
    ]
    terminal = StringIO()

    vivado.export_block_design(
        command,
        tmp_path,
        raw_export,
        committed,
        tmp_path,
        "gpgpu_block_design",
        terminal=terminal,
    )

    assert "up to date" in terminal.getvalue()
    assert "WARNING" not in terminal.getvalue()


def test_export_rejects_empty_design_without_overwriting_source(tmp_path: Path) -> None:
    raw_export = tmp_path / "empty.raw.tcl"
    committed = tmp_path / "create_block_design.tcl"
    committed.write_text("# working source\n", encoding="utf-8")
    empty_export = (
        "# CHANGE DESIGN NAME HERE\nvariable design_name\n"
        'set design_name gpgpu_block_design\ncreate_root_design ""\n'
    )
    command = [
        sys.executable,
        "-c",
        f"from pathlib import Path; Path({str(raw_export)!r}).write_text({empty_export!r})",
    ]
    with pytest.raises(RuntimeError, match="GPGPU_0"):
        vivado.export_block_design(
            command,
            tmp_path,
            raw_export,
            committed,
            tmp_path,
            "gpgpu_block_design",
        )
    assert committed.read_text(encoding="utf-8") == "# working source\n"
    assert not raw_export.exists()
