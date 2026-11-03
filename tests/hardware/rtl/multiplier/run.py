#!/usr/bin/env python3
"""Run multiplier unit/SMX regressions without modifying existing cases or benches."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
PACKAGES = ("gpu_pkg", "riscv_pkg", "alu_pkg", "control_pkg", "warp_pkg", "pipeline_pkg")


def run(command: list[str], cwd: Path, log: Path) -> str:
    with log.open("w") as output:
        result = subprocess.run(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT)
    text = log.read_text()
    if result.returncode or re.search(r"\[(?:FAIL|ERROR|Error)\]|%Error|Fatal:", text):
        raise RuntimeError(f"Command failed ({result.returncode}): {shlex.join(command)}\n{text[-8000:]}\nFull log: {log}")
    return text


def sources(rtl: Path) -> list[str]:
    interface = rtl / "memory/MemoryInterface.sv"
    return [
        *(str(rtl / f"packages/{p}.sv") for p in PACKAGES), str(interface),
        *(str(p) for directory in (rtl, rtl / "control", rtl / "memory", rtl / "sp")
          for p in sorted(directory.glob("*.sv")) if p != interface),
    ]


def compile_tb(args, rtl: Path, bench: Path, top: str, build: Path, parameters: list[str], unit=False):
    build.mkdir(parents=True, exist_ok=True)
    rtl_sources = sources(rtl)
    if unit:
        rtl_sources = [str(rtl / f"packages/{p}.sv") for p in PACKAGES]
        rtl_sources += [str(rtl / f"sp/{p}.sv") for p in ("ALU", "Multiplier", "HazardUnit")]
    command = [
        args.verilator, "--binary", "--timing", "--assert", "--autoflush", "-Wno-fatal",
        "--timescale", "1ns/1ps", f"-I{rtl}", "-DSIM", "--top-module", top,
        "--Mdir", str(build), "-o", "sim", "-j", str(args.jobs),
        "-MAKEFLAGS", shlex.join([f"CXX={args.cxx}", f"LINK={args.cxx}"]),
        *parameters, *rtl_sources, str(bench),
    ]
    run(command, REPO, build / "build.log")
    warnings = re.findall(r"^%Warning[^\n]*", (build / "build.log").read_text(), re.M)
    print(f"Built {build.name}: {len(warnings)} warnings (see {build / 'build.log'})", flush=True)
    return build / "sim"


def smx_bench(latency: int, baseline: bool) -> str:
    text = (HERE.parent / "tb_GPGPU.sv").read_text()
    if not baseline:
        text = text.replace('.MEMORY_INIT("")', f'.MEMORY_INIT(""), .MUL_LATENCY({latency})')
    # Negedge observations capture settled state, including reset and global stalls.
    # Packed EXMEM layout is unchanged by the mul3_valid -> mul_valid field rename.
    extra = '''
    integer state_fd;
    initial state_fd = $fopen("state_trace.txt", "w");
    always @(negedge uut_clk) begin
        #1;
        $fdisplay(state_fd, "SM %h %h %h %h %h %h %h %h %h %h",
            rst, UUT.smx.global_stall, UUT.smx.data_hazard, UUT.smx.flush,
            UUT.smx.program_counter, UUT.smx.ifid_program_counter, UUT.smx.idex,
            UUT.smx.ex_branch_taken, UUT.smx.ex_beq_target_idx, UUT.core_complete);
    end
    for (genvar tc = 0; tc < NUM_CORES; tc++) begin : state_probes
        always @(negedge uut_clk) begin
            #1;
            $fdisplay(state_fd, "CORE %0d %h %h %h %h %h %h %h %h %h %h %h", tc,
                UUT.smx.cores[tc].core.exmem, UUT.smx.cores[tc].core.memwb,
                UUT.smx.cores[tc].core.ex_actual_alu_in_a,
                UUT.smx.cores[tc].core.ex_actual_alu_in_b,
                UUT.smx.cores[tc].core.mul_not_ready,
                UUT.smx.cores[tc].core.wb_wdata,
                UUT.smx.sp_mem[tc].addr, UUT.smx.sp_mem[tc].ren,
                UUT.smx.sp_mem[tc].wen, UUT.smx.sp_mem[tc].wdata,
                UUT.smx.sp_mem[tc].rdata);
            for (int tr = 0; tr < 32; tr++)
                $fdisplay(state_fd, "REG %0d %0d %h", tc, tr, core_reg_probes[tc][tr]);
        end
    end
'''
    return text.replace("endmodule", extra + "\nendmodule")


def prepare_cases(args, runtime: Path) -> int:
    cases = runtime / "cases"
    cases.mkdir(parents=True, exist_ok=True)
    existing = sorted(HERE.parent.glob("cases/test*/program.asm"), key=lambda p: int(p.parent.name[4:]))
    indices = [int(p.parent.name[4:]) for p in existing]
    if indices != list(range(1, len(existing)+1)):
        raise RuntimeError("Existing cases must be contiguous for the existing SMX bench")
    for program in existing:
        dest = cases / program.parent.name
        dest.mkdir(exist_ok=True)
        shutil.copy2(program, dest / "program.asm")
        seed = program.with_name("dmem_seed.mem")
        if seed.exists():
            shutil.copy2(seed, dest / seed.name)
    directed = cases / f"test{len(existing)+1}"
    directed.mkdir(exist_ok=True)
    shutil.copy2(HERE / "program.asm", directed / "program.asm")
    run([sys.executable, str(REPO / "tools/tests/assembler.py")], runtime, runtime / "assemble.log")
    run([sys.executable, str(REPO / "tools/tests/expected_generator.py"), "--num-cores", str(args.cores)],
        runtime, runtime / "expected.log")
    return len(existing)+1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--cxx", default="g++")
    parser.add_argument("--make", default="make")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--cores", type=int, default=4)
    parser.add_argument("--latencies", nargs="+", type=int, default=[1, 2, 3, 5])
    parser.add_argument("--build-dir", type=Path, default=REPO / "build/tests/multiplier")
    parser.add_argument("--baseline-rtl", type=Path, help="Pre-refactor hardware/rtl/gpgpu snapshot (optional cycle equivalence)")
    args = parser.parse_args()
    if min(args.latencies + [args.cores, args.jobs]) < 1:
        parser.error("latencies, cores and jobs must be positive")
    args.build_dir = args.build_dir.resolve()
    args.build_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MAKE"] = args.make
    rtl = REPO / "hardware/rtl/gpgpu"
    report = {"cores": args.cores, "latencies": {}, "baseline_equivalence": "not requested"}
    traces = {}
    for latency in args.latencies:
        unit_build = args.build_dir / f"unit_l{latency}"
        unit = compile_tb(args, rtl, HERE / "tb_multiplier.sv", "tb_multiplier", unit_build,
                          [f"-GLATENCY={latency}"], unit=True)
        unit_text = run([str(unit)], unit_build, unit_build / "simulation.log")
        if f"PASS multiplier/ALU/hazard LATENCY={latency}" not in unit_text:
            raise RuntimeError("Unit test did not reach its PASS marker")
        build = args.build_dir / f"smx_l{latency}"
        build.mkdir(exist_ok=True)
        bench = build / "tb_smx.sv"
        bench.write_text(smx_bench(latency, False))
        count = prepare_cases(args, build)
        sim = compile_tb(args, rtl, bench, "tb_GPGPU_smx_only", build, [f"-GNUM_CORES={args.cores}"])
        text = run([str(sim), f"+TEST_END={count}"], build, build / "simulation.log")
        passed = re.findall(r"\[SUCCESS\] Test (\d+) is correct", text)
        if [int(x) for x in passed] != list(range(1, count+1)):
            raise RuntimeError(f"Expected all {count} tests, got {passed}")
        traces[latency] = build / "state_trace.txt"
        report["latencies"][latency] = {"unit": "PASS", "smx_cases": count, "smx": "PASS"}
        print(f"PASS latency={latency}: unit + all {count} SMX cases on {args.cores} cores", flush=True)
    if args.baseline_rtl:
        if 3 not in traces:
            raise RuntimeError("Baseline equivalence requires latency 3 in --latencies")
        build = args.build_dir / "baseline_l3"
        build.mkdir(exist_ok=True)
        bench = build / "tb_smx.sv"
        bench.write_text(smx_bench(3, True))
        count = prepare_cases(args, build)
        sim = compile_tb(args, args.baseline_rtl.resolve(), bench, "tb_GPGPU_smx_only", build,
                         [f"-GNUM_CORES={args.cores}"])
        text = run([str(sim), f"+TEST_END={count}"], build, build / "simulation.log")
        if len(re.findall(r"\[SUCCESS\] Test (\d+) is correct", text)) != count:
            raise RuntimeError("Baseline did not pass every case")
        old = (build / "state_trace.txt").read_bytes()
        new = traces[3].read_bytes()
        if old != new:
            raise RuntimeError(f"Cycle equivalence failed: compare {build / 'state_trace.txt'} and {traces[3]}")
        for index in range(1, count+1):
            old_pc = build / f"cases/test{index}/trace.csv"
            new_pc = traces[3].parent / f"cases/test{index}/trace.csv"
            if old_pc.read_bytes() != new_pc.read_bytes():
                raise RuntimeError(f"PC cycle equivalence failed for test {index}")
        report["baseline_equivalence"] = {"result": "PASS", "cases": count, "state_trace_bytes": len(old)}
        print(f"PASS original/default cycle equivalence: {count} cases, {len(old)} trace bytes", flush=True)
    (args.build_dir / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
