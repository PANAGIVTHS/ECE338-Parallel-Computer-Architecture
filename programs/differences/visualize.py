#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

try:
    import matplotlib.pyplot as plt
except ImportError as exc:
    raise SystemExit(
        "visualize.py needs matplotlib.\n"
        "Install it with:\n"
        "  pip install matplotlib"
    ) from exc


DEFAULT_INPUT = Path("data.csv")
DEFAULT_OUTPUT = Path("adjacent_differences.png")


def parse_int(value: str) -> int:
    return int(value, 0)


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def available_calls(rows: list[dict[str, str]]) -> list[int]:
    calls = sorted({parse_int(row["call"]) for row in rows})
    return calls


def select_call(rows: list[dict[str, str]], call: int | None) -> tuple[int, list[dict[str, str]]]:
    calls = available_calls(rows)
    if not calls:
        raise SystemExit("No call values found in CSV.")

    selected_call = calls[-1] if call is None else call
    selected_rows = [row for row in rows if parse_int(row["call"]) == selected_call]

    if not selected_rows:
        raise SystemExit(f"Call {selected_call} was not found. Available calls: {calls}")

    selected_rows.sort(key=lambda row: parse_int(row["index"]))
    return selected_call, selected_rows


def validate_columns(rows: list[dict[str, str]]) -> None:
    required = {"call", "index", "data_left", "data_right", "diff", "expected", "ok"}

    if not rows:
        raise SystemExit("CSV file is empty.")

    missing = required - set(rows[0])
    if missing:
        raise SystemExit(
            "Unsupported CSV format. Missing column(s): "
            + ", ".join(sorted(missing))
            + "\nExpected columns: call,index,data_left,data_right,diff,expected,ok"
        )


def plot_call(rows: list[dict[str, str]], *, call: int, output: Path, title: str | None) -> None:
    indices = [parse_int(row["index"]) for row in rows]
    data_left = [parse_int(row["data_left"]) for row in rows]
    data_right = [parse_int(row["data_right"]) for row in rows]
    diff = [parse_int(row["diff"]) for row in rows]
    expected = [parse_int(row["expected"]) for row in rows]
    ok = [parse_int(row["ok"]) for row in rows]

    mismatches = [i for i, ok_value in zip(indices, ok) if ok_value == 0]

    fig = plt.figure(figsize=(12, 8))
    fig.suptitle(title or f"Adjacent Differences - call {call}", fontsize=14)

    ax1 = fig.add_subplot(3, 1, 1)
    ax1.plot(indices, data_left, marker="o", label="data[i]")
    ax1.plot(indices, data_right, marker="o", label="data[i+1]")
    ax1.set_ylabel("Input values")
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    ax2 = fig.add_subplot(3, 1, 2)
    ax2.bar(indices, diff, label="diff[i]")
    ax2.plot(indices, expected, marker="o", linestyle="--", label="expected")
    ax2.set_ylabel("Difference")
    ax2.grid(True, axis="y", alpha=0.3)
    ax2.legend()

    ax3 = fig.add_subplot(3, 1, 3)
    ax3.bar(indices, ok)
    ax3.set_ylim(-0.1, 1.1)
    ax3.set_xlabel("Index")
    ax3.set_ylabel("OK")
    ax3.set_yticks([0, 1])
    ax3.grid(True, axis="y", alpha=0.3)

    if mismatches:
        ax3.set_title(f"Mismatches at indices: {mismatches}")
    else:
        ax3.set_title("All outputs match expected values")

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(output, dpi=150)
    plt.close(fig)

    print(f"[INFO] Wrote {output}")
    if mismatches:
        print(f"[ERROR] Found {len(mismatches)} mismatch(es): {mismatches}")
    else:
        print(f"[SUCCESS] All {len(indices)} adjacent differences are correct")


def write_text_summary(rows: list[dict[str, str]], *, call: int, output: Path) -> None:
    total = len(rows)
    failures = sum(1 for row in rows if parse_int(row["ok"]) == 0)

    with output.open("w") as f:
        f.write(f"Adjacent differences summary for call {call}\n")
        f.write("=" * 48 + "\n")
        f.write(f"Total outputs : {total}\n")
        f.write(f"Correct       : {total - failures}\n")
        f.write(f"Failures      : {failures}\n\n")

        if failures:
            f.write("Mismatches:\n")
            for row in rows:
                if parse_int(row["ok"]) == 0:
                    index = parse_int(row["index"])
                    data_left = parse_int(row["data_left"])
                    data_right = parse_int(row["data_right"])
                    diff = parse_int(row["diff"])
                    expected = parse_int(row["expected"])
                    f.write(
                        f"  index={index}: "
                        f"data_right({data_right}) - data_left({data_left}) "
                        f"= expected {expected}, got {diff}\n"
                    )

    print(f"[INFO] Wrote {output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Visualize and verify adjacent-differences FPGA output CSV."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input CSV file")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output PNG file")
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("adjacent_differences_summary.txt"),
        help="Output text summary file",
    )
    parser.add_argument(
        "--call",
        type=int,
        default=None,
        help="Kernel call to visualize. Default: latest call in the CSV.",
    )
    parser.add_argument("--title", default=None, help="Custom plot title")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input CSV not found: {args.input}")

    rows = load_rows(args.input)
    validate_columns(rows)

    call, selected_rows = select_call(rows, args.call)

    plot_call(selected_rows, call=call, output=args.output, title=args.title)
    write_text_summary(selected_rows, call=call, output=args.summary)


if __name__ == "__main__":
    main()
