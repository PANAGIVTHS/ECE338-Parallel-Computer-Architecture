from __future__ import annotations

import argparse
import csv
from pathlib import Path

try:
    import matplotlib

    matplotlib.use("Agg")  # File-only backend: works over SSH/Docker.
    import matplotlib.animation as animation
    import matplotlib.pyplot as plt
except ImportError as exc:
    raise SystemExit(
        "visualize.py needs matplotlib and pillow. Install them, or run: "
        "uv run --with matplotlib --with pillow python visualize.py"
    ) from exc


INPUT_CSV = Path("data.csv")
OUTPUT_GIF = Path("nbody_animation.gif")

FPS = 30
TRAIL_LENGTH = 60
PADDING = 15

BODY_COLORS = [
    "#FFD700", "#1E90FF", "#FF4500", "#32CD32",
    "#DA70D6", "#00CED1", "#FF69B4", "#ADFF2F",
]


def parse_int(value: str | None, *, field: str) -> int:
    if value is None or value == "":
        raise ValueError(f"Missing CSV field: {field}")
    return int(value, 0)


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def wide_body_indices(row: dict[str, str]) -> list[int]:
    """Detect xN/yN pairs in the FPGA wide format."""
    return sorted(
        int(name[1:])
        for name in row
        if name.startswith("x")
        and name[1:].isdigit()
        and f"y{name[1:]}" in row
    )


def rows_to_frames(rows: list[dict[str, str]]) -> list[dict[int, tuple[int, int]]]:
    """Normalize supported CSV formats into frames.

    Return:
        [
            {body_id: (x, y), ...},   # frame 0
            {body_id: (x, y), ...},   # frame 1
            ...
        ]
    """
    if not rows:
        return []

    first = rows[0]

    # Format 1: wide FPGA data.csv: step,x0,y0,x1,y1,...
    detected = wide_body_indices(first)
    if detected:
        frames: list[dict[int, tuple[int, int]]] = []
        for row in rows:
            frame: dict[int, tuple[int, int]] = {}
            for body in detected:
                x = parse_int(row.get(f"x{body}"), field=f"x{body}")
                y = parse_int(row.get(f"y{body}"), field=f"y{body}")
                frame[body] = (x, y)
            frames.append(frame)
        return frames

    fieldnames = set(first.keys())

    # Format 3: long format with explicit steps: step,body,x,y
    if {"step", "body", "x", "y"}.issubset(fieldnames):
        grouped: dict[int, dict[int, tuple[int, int]]] = {}
        for row in rows:
            step = parse_int(row.get("step"), field="step")
            body = parse_int(row.get("body"), field="body")
            x = parse_int(row.get("x"), field="x")
            y = parse_int(row.get("y"), field="y")
            grouped.setdefault(step, {})[body] = (x, y)
        return [grouped[step] for step in sorted(grouped)]

    # Format 2: long single-frame native/debug format: body,x,y
    if {"body", "x", "y"}.issubset(fieldnames):
        frame: dict[int, tuple[int, int]] = {}
        for row in rows:
            body = parse_int(row.get("body"), field="body")
            x = parse_int(row.get("x"), field="x")
            y = parse_int(row.get("y"), field="y")
            frame[body] = (x, y)
        return [frame]

    # Format 4: older native format: body,x,y,new_x,new_y
    # This branch is intentionally after body,x,y. If new_x/new_y exist, prefer them.
    if {"body", "new_x", "new_y"}.issubset(fieldnames):
        frame = {}
        for row in rows:
            body = parse_int(row.get("body"), field="body")
            x = parse_int(row.get("new_x"), field="new_x")
            y = parse_int(row.get("new_y"), field="new_y")
            frame[body] = (x, y)
        return [frame]

    raise SystemExit(
        "Unsupported CSV format. Expected either:\n"
        "  step,x0,y0,x1,y1,...\n"
        "  body,x,y\n"
        "  step,body,x,y\n"
        "  body,x,y,new_x,new_y"
    )


def frames_to_bodies(frames: list[dict[int, tuple[int, int]]]) -> list[dict[str, object]]:
    body_ids = sorted({body for frame in frames for body in frame})
    bodies: list[dict[str, object]] = []

    for body in body_ids:
        xs: list[int] = []
        ys: list[int] = []

        last_x = 0
        last_y = 0
        have_last = False

        for frame in frames:
            if body in frame:
                last_x, last_y = frame[body]
                have_last = True
            elif not have_last:
                # Sparse leading frames are unusual; keep body at origin until first value.
                last_x, last_y = 0, 0
            xs.append(last_x)
            ys.append(last_y)

        bodies.append({"idx": body, "xs": xs, "ys": ys})

    return bodies


def calculate_bounds(bodies: list[dict[str, object]]) -> tuple[int, int, int, int]:
    xs = [x for body in bodies for x in body["xs"]]  # type: ignore[index]
    ys = [y for body in bodies for y in body["ys"]]  # type: ignore[index]

    min_x, max_x = min(xs) - PADDING, max(xs) + PADDING
    min_y, max_y = min(ys) - PADDING, max(ys) + PADDING

    if min_x == max_x:
        max_x = min_x + 1
    if min_y == max_y:
        max_y = min_y + 1

    return min_x, max_x, min_y, max_y


def make_animation(
    *,
    frames: list[dict[int, tuple[int, int]]],
    bodies: list[dict[str, object]],
    output_path: Path,
    fps: int,
    trail_length: int,
) -> None:
    fig, ax = plt.subplots(figsize=(8, 8))
    fig.patch.set_facecolor("#0b0f19")
    ax.set_facecolor("#0b0f19")
    ax.set_title("N-body GPGPU Output", color="white")
    ax.set_xlabel("X Position", color="white")
    ax.set_ylabel("Y Position", color="white")
    ax.tick_params(colors="white")
    ax.grid(True, linestyle="--", alpha=0.25)

    min_x, max_x, min_y, max_y = calculate_bounds(bodies)
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)

    for spine in ax.spines.values():
        spine.set_color("white")

    scatters = []
    trails = []

    for body_num, body in enumerate(bodies):
        body_idx = body["idx"]  # type: ignore[index]
        color = BODY_COLORS[body_num % len(BODY_COLORS)]
        size = 45
        edge_color = "black"
        zorder = 3

        if body_idx == 0:
            color = "#000000"
            edge_color = "#FFD700"
            size = 140
            zorder = 4

        scatter = ax.scatter([], [], c=color, s=size, edgecolors=edge_color, zorder=zorder)
        trail, = ax.plot([], [], c=color, alpha=0.55, linewidth=1.5, zorder=2)
        scatters.append(scatter)
        trails.append(trail)

    step_text = ax.text(
        0.02,
        0.97,
        "",
        transform=ax.transAxes,
        color="white",
        fontsize=12,
        fontfamily="monospace",
        va="top",
    )

    def update(frame_idx: int):
        start = max(0, frame_idx - trail_length)

        for body_num, body in enumerate(bodies):
            xs = body["xs"]  # type: ignore[index]
            ys = body["ys"]  # type: ignore[index]

            x = xs[frame_idx]
            y = ys[frame_idx]

            scatters[body_num].set_offsets([[x, y]])
            trails[body_num].set_data(xs[start:frame_idx + 1], ys[start:frame_idx + 1])

        step_text.set_text(f"frame {frame_idx} / {len(frames) - 1}")
        return scatters + trails + [step_text]

    # A one-frame GIF is valid, but FuncAnimation needs at least one frame.
    interval_ms = 1000 / fps
    anim = animation.FuncAnimation(fig, update, frames=len(frames), interval=interval_ms, blit=True)
    writer = animation.PillowWriter(fps=fps)
    anim.save(output_path, writer=writer)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render nbody CSV data as a matplotlib GIF.")
    parser.add_argument("--input", type=Path, default=INPUT_CSV, help="CSV generated by fpga.py or nbody_x86")
    parser.add_argument("--output", type=Path, default=OUTPUT_GIF, help="GIF file to write")
    parser.add_argument("--fps", type=int, default=FPS, help="Frames per second for the output GIF")
    parser.add_argument("--trail", type=int, default=TRAIL_LENGTH, help="Number of previous frames to show as a trail")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input.exists():
        raise SystemExit(f"{args.input} not found.")

    rows = load_rows(args.input)
    if not rows:
        raise SystemExit(f"{args.input} is empty.")

    frames = rows_to_frames(rows)
    if not frames:
        raise SystemExit(f"{args.input} did not contain any frames.")

    bodies = frames_to_bodies(frames)
    if not bodies:
        raise SystemExit(f"{args.input} did not contain any bodies.")

    make_animation(
        frames=frames,
        bodies=bodies,
        output_path=args.output,
        fps=args.fps,
        trail_length=args.trail,
    )

    print(f"Wrote {args.output} with {len(bodies)} bodies and {len(frames)} frames")


if __name__ == "__main__":
    main()
