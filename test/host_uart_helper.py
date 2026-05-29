#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

BAREMETAL_DIR = Path(__file__).resolve().parents[1] / "host" / "baremetal"
sys.path.insert(0, str(BAREMETAL_DIR))

from gpgpu_uart import (
    DEPTH,
    GpgpuUartMonitor,
    normalize_word,
    read_mem_file,
    trim_program_at_ret,
    write_mem_file,
)


def print_words(words: dict[int, str]) -> None:
    for addr in sorted(words):
        print(f"{addr:04d}: {words[addr]}")


def dump_or_save(words: dict[int, str], output: Path | None) -> None:
    if output is None:
        print_words(words)
    else:
        write_mem_file(output, words)
        print(f"[SUCCESS] Wrote {len(words)} words to {output}")


def add_offset_count(parser, default_count=None):
    parser.add_argument("--offset", type=int, default=0, help="Starting memory word offset (default: 0)")
    if default_count is None:
        parser.add_argument("--count", type=int, required=True, help="Number of words")
    else:
        parser.add_argument("--count", "--size", dest="count", type=int, default=default_count,
                            help=f"Number of words (default: {default_count})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GPGPU baremetal UART host helper")
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/ttyUSB1")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--verbose", action="store_true", help="Print UART traffic")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("help", help="Print monitor help")
    sub.add_parser("status", help="Read and print monitor/core status")
    sub.add_parser("run", help="Start the GPGPU and wait for dumping state")
    sub.add_parser("done", help="Send READ_DONE and wait for loading state")

    p = sub.add_parser("read-imem", help="Read one IMEM word")
    p.add_argument("addr", type=int, help="IMEM word address")

    p = sub.add_parser("read-dmem", help="Read one DMEM word")
    p.add_argument("addr", type=int, help="DMEM word address")

    p = sub.add_parser("write-imem", help="Write one IMEM word")
    p.add_argument("addr", type=int, help="IMEM word address")
    p.add_argument("word", help="Word value, e.g. 00000013 or 0x13")

    p = sub.add_parser("write-dmem", help="Write one DMEM word")
    p.add_argument("addr", type=int, help="DMEM word address")
    p.add_argument("word", help="Word value, e.g. 00000014 or 0x14")

    p = sub.add_parser("load-imem", help="Load a .mem file into IMEM")
    p.add_argument("file", type=Path)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--trim", action="store_true", help="Stop loading after RET instruction")
    p.add_argument("--mode", choices=("bin", "ascii"), default="bin", help="UART load protocol (default: bin)")

    p = sub.add_parser("load-dmem", help="Load a .mem file into DMEM")
    p.add_argument("file", type=Path)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--mode", choices=("bin", "ascii"), default="bin", help="UART load protocol (default: bin)")

    p = sub.add_parser("clean-imem", help="Fill an IMEM range with zeros")
    add_offset_count(p, default_count=DEPTH)
    p.add_argument("--mode", choices=("bin", "ascii"), default="bin")

    p = sub.add_parser("clean-dmem", help="Fill a DMEM range with zeros")
    add_offset_count(p, default_count=DEPTH)
    p.add_argument("--mode", choices=("bin", "ascii"), default="bin")

    p = sub.add_parser("dump-imem", help="Dump an IMEM range using ASCII monitor output")
    add_offset_count(p)
    p.add_argument("--output", "-o", type=Path, help="Optional .mem output file")

    p = sub.add_parser("dump-dmem", help="Dump a DMEM range")
    add_offset_count(p)
    p.add_argument("--mode", choices=("bin", "ascii"), default="bin", help="UART dump protocol (default: bin)")
    p.add_argument("--output", "-o", type=Path, help="Optional .mem output file")

    p = sub.add_parser("raw", help="Send a raw monitor command and print output up to prompt")
    p.add_argument("monitor_command", nargs=argparse.REMAINDER, help="Command tokens to send")

    return parser


def load_words_from_file(path: Path, trim: bool = False) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(path)
    words = read_mem_file(path)
    return trim_program_at_ret(words) if trim else words


def main():
    parser = build_parser()
    args = parser.parse_args()

    print(f"[INFO] Opening UART {args.port} @ {args.baud}...")
    try:
        with GpgpuUartMonitor(args.port, args.baud, verbose=args.verbose) as uart:
            if args.command == "help":
                print(uart.help(), end="")

            elif args.command == "status":
                status = uart.status()
                print(status.get("text", ""), end="")

            elif args.command == "run":
                print(uart.run(), end="")

            elif args.command == "done":
                print(uart.done(), end="")

            elif args.command == "read-imem":
                print(f"IMEM[{args.addr}] = 0x{uart.read_imem(args.addr)}")

            elif args.command == "read-dmem":
                print(f"DMEM[{args.addr}] = 0x{uart.read_dmem(args.addr)}")

            elif args.command == "write-imem":
                uart.write_imem(args.addr, args.word)
                print(f"[SUCCESS] IMEM[{args.addr}] <- 0x{normalize_word(args.word)}")

            elif args.command == "write-dmem":
                uart.write_dmem(args.addr, args.word)
                print(f"[SUCCESS] DMEM[{args.addr}] <- 0x{normalize_word(args.word)}")

            elif args.command == "load-imem":
                words = load_words_from_file(args.file, trim=args.trim)
                if args.mode == "bin":
                    uart.load_imem_bin(words, offset=args.offset)
                else:
                    uart.load_imem_ascii(words, offset=args.offset)
                print(f"[SUCCESS] Loaded {len(words)} IMEM words at offset {args.offset} from {args.file}")

            elif args.command == "load-dmem":
                words = load_words_from_file(args.file)
                if args.mode == "bin":
                    uart.load_dmem_bin(words, offset=args.offset)
                else:
                    uart.load_dmem_ascii(words, offset=args.offset)
                print(f"[SUCCESS] Loaded {len(words)} DMEM words at offset {args.offset} from {args.file}")

            elif args.command == "clean-imem":
                zeros = ["00000000"] * args.count
                if args.mode == "bin":
                    uart.load_imem_bin(zeros, offset=args.offset)
                else:
                    uart.load_imem_ascii(zeros, offset=args.offset)
                print(f"[SUCCESS] Cleared {args.count} IMEM words at offset {args.offset}")

            elif args.command == "clean-dmem":
                zeros = ["00000000"] * args.count
                if args.mode == "bin":
                    uart.load_dmem_bin(zeros, offset=args.offset)
                else:
                    uart.load_dmem_ascii(zeros, offset=args.offset)
                print(f"[SUCCESS] Cleared {args.count} DMEM words at offset {args.offset}")

            elif args.command == "dump-imem":
                words = uart.dump_imem_ascii(args.count, offset=args.offset)
                dump_or_save(words, args.output)

            elif args.command == "dump-dmem":
                if args.mode == "bin":
                    words = uart.dump_dmem_bin(args.count, offset=args.offset)
                else:
                    words = uart.dump_dmem_ascii(args.count, offset=args.offset)
                dump_or_save(words, args.output)

            elif args.command == "raw":
                if not args.monitor_command:
                    raise ValueError("raw requires a monitor command")
                print(uart.command(" ".join(args.monitor_command)), end="")

    except Exception as exc:
        print(f"[ERROR] Operation failed: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
