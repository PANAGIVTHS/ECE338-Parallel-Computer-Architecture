#!/usr/bin/env python3
"""Reproducible ECALL regression. Uses Verilator and the RV32 bare-metal GCC.

Run from anywhere: python tests/hardware/rtl/ecall/run.py [--cores 4 32]
Build products and copied directed cases stay under build/tests/ecall-current.
"""
from pathlib import Path
import argparse

import json
import os
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent

def run(command, cwd, log):
    result = subprocess.run([str(x) for x in command], cwd=cwd, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(map(str,command))}\n{result.stdout[-8000:]}")
    return result.stdout

def sources(root):
    rtl = root / "hardware/rtl/gpgpu"
    manifest = (root / "config/profiles/default.yaml").read_text()
    ordered_block = manifest.split("    ordered:\n",1)[1].split("  vivado:",1)[0]
    ordered = [rtl / x for x in re.findall(r"^      - (.+)$",ordered_block,re.M)]
    rest = sorted(p for p in rtl.rglob("*") if p.suffix in (".sv",".v")
                  and "experimental" not in p.parts and p.name != "HostControllerProcessor.sv")
    return ordered + [p for p in rest if p not in ordered]

def build(root, out, top, bench, cores, extra=()):
    command = ["verilator","--binary","--timing","--assert","--autoflush","-Wno-fatal",
               "--timescale","1ns/1ps",f"-I{root / 'hardware/rtl/gpgpu'}","-DSIM",
               "--top-module",top,f"-GNUM_CORES={cores}","-j","2",
               "--Mdir",out,"-o","sim",*extra,*sources(root),bench]
    run(command,root,out / "build.log")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cores",type=int,nargs="+",default=[4,32])
    parser.add_argument("--build-root",type=Path,default=ROOT / "build/tests/ecall-current")
    parser.add_argument("--rtl-root",type=Path,default=ROOT,
                        help="Optional alternate source snapshot for negative/baseline checks")
    parser.add_argument("--skip-directed",action="store_true")
    parser.add_argument("--random-iterations",type=int,default=25)
    args = parser.parse_args()
    out = args.build_root.resolve(); out.mkdir(parents=True,exist_ok=True)
    rtl_root = args.rtl_root.resolve()
    prefix = os.environ.get("CROSS_PREFIX","riscv64-unknown-elf")
    gcc = prefix+"-gcc"
    for command in ["verilator",gcc,prefix+"-objdump",prefix+"-objcopy"]:
        if not shutil.which(command): raise RuntimeError(f"Missing {command}; activate your toolchain environment")
    elf = out / "kernel.elf"
    run([gcc,"-O2","-march=rv32im","-mabi=ilp32","-ffreestanding","-fno-builtin",
         "-fomit-frame-pointer","-ffixed-x31","-ffunction-sections","-fdata-sections",
         "-msmall-data-limit=0","-mno-relax","-nostdlib","-nostartfiles",
         f"-I{ROOT / 'software/programs'}",f"-Wl,-T,{ROOT / 'software/programs/gpgpu.ld'}",
         "-Wl,--build-id=none",HERE / "kernel.c","-o",elf],ROOT,out / "compile.log")
    disasm = run([prefix+"-objdump","-d","-M","no-aliases,numeric",elf],ROOT,out / "kernel.disasm")
    instructions = re.findall(r"^\s*[0-9a-f]+:\s+([0-9a-f]{8})\s+(.+)$",disasm,re.M)
    if not any(word == "00000073" for word,_ in instructions): raise RuntimeError("No runtime ECALL")
    if any(text.startswith("auipc") for _,text in instructions): raise RuntimeError("C fixture unexpectedly needs unsupported AUIPC")
    run([prefix+"-objcopy","-O","binary","--only-section=.text",elf,out / "kernel.bin"],ROOT,out / "objcopy.log")
    raw = (out / "kernel.bin").read_bytes()
    # Both existing test benches and the default architecture use 2048 IMEM words.
    if len(raw)%4 or len(raw)>2048*4: raise RuntimeError("Invalid fixture image size")
    words = [int.from_bytes(raw[i:i+4],"little") for i in range(0,len(raw),4)]
    image = out / "kernel.mem"
    image.write_text("".join(f"{w:08x}\n" for w in words+[0]*(2048-len(words))))
    results=[]
    for cores in args.cores:
        dest=out / f"cores_{cores}"
        build(rtl_root,dest,"tb_ecall",HERE / "tb_ecall.sv",cores)
        output=run([dest / "sim",f"+C_IMAGE={image}"],out,dest / "simulation.log")
        match=re.search(r"ECALL PASS cases=(\d+) cores=(\d+)",output)
        if not match or int(match[2])!=cores: raise RuntimeError("Missing ECALL PASS summary")
        expected=20 if cores>1 else 19
        if int(match[1])!=expected: raise RuntimeError(f"Expected {expected} cases, got {match[1]}")
        print(output.strip(),flush=True)
        results.append({"cores":cores,"cases":int(match[1])})
    if not args.skip_directed:
        cases=out / "cases"
        if cases.exists(): shutil.rmtree(cases)
        shutil.copytree(ROOT / "tests/hardware/rtl/cases",cases,
                        ignore=shutil.ignore_patterns("*.mem","trace.csv"))
        for cores in args.cores:
            run([sys.executable,ROOT / "tools/tests/assembler.py"],out,out / "assemble.log")
            run([sys.executable,ROOT / "tools/tests/expected_generator.py","--num-cores",cores],out,out / f"expected_{cores}.log")
            dest=out / f"directed_{cores}"
            params=[f"-G{name}={value}" for name,value in dict(INTERFACE_VERSION=1,CLOCK_KHZ=100000,BUILD_HASH=0,BUILD_DIRTY=0,DDR_ENABLE=0).items()]
            build(rtl_root,dest,"tb_GPGPU_smx_only",ROOT / "tests/hardware/rtl/tb_GPGPU.sv",cores,params)
            output=run([dest / "sim"],out,dest / "simulation.log")
            passed=re.findall(r"\[SUCCESS\] Test (\d+) is correct",output)
            expected=sorted(int(p.name[4:]) for p in cases.glob("test*") if (p / "program.asm").is_file())
            if sorted(map(int,passed))!=expected: raise RuntimeError("Directed test count mismatch")
            print(f"DIRECTED PASS cores={cores} cases={len(passed)}",flush=True)
            results.append({"directed_cores":cores,"cases":len(passed)})
            axi_dest=out / f"axi_{cores}"
            build(rtl_root,axi_dest,"tb_GPGPU_e2e",ROOT / "tests/hardware/rtl/tb_GPGPU_e2e.sv",cores,params)
            settings=dict(TEST_ROOT=cases,CASE_PREFIX="test",TEST_IDX=1,PROGRAM_FILE="program.mem",
                          DATA_FILE="data.mem",CLOCK_PERIOD_NS=10,RESET_CYCLES=20,
                          TEST_TIMEOUT_CYCLES=10000,AXI_TIMEOUT_CYCLES=1000,UNMAPPED_ADDR="00008000")
            output=run([axi_dest / "sim",*(f"+{k}={v}" for k,v in settings.items())],out,axi_dest / "simulation.log")
            passed=re.findall(r"\[SUCCESS\] Test (\d+) passed",output)
            if sorted(map(int,passed))!=expected: raise RuntimeError("AXI test count mismatch")
            print(f"AXI PASS cores={cores} cases={len(passed)} (including host fault/status/IRQ checks)",flush=True)
            results.append({"axi_cores":cores,"cases":len(passed)})
            if args.random_iterations:
                output=run([sys.executable,ROOT / "tools/tests/random_tester.py",
                            "--iterations",args.random_iterations,"--num-cores",cores,"--seed",4242,
                            "--simulator",dest / "sim","--test-root",out,"--log",dest / "random.log"],
                           out,dest / "random_runner.log")
                if f"All {args.random_iterations} random tests passed" not in output:
                    raise RuntimeError("Missing random test success summary")
                print(f"RANDOM PASS cores={cores} cases={args.random_iterations} seed=4242",flush=True)
                results.append({"random_cores":cores,"cases":args.random_iterations,"seed":4242})
    (out / "results.json").write_text(json.dumps(results,indent=2)+"\n")
    print(f"Results: {out / 'results.json'}")

if __name__ == "__main__":
    main()
