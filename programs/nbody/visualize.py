#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError as exc:
    raise SystemExit(
        "visualize.py needs opencv-python and numpy.\n"
        "Install them with:\n"
        "  pip install opencv-python numpy\n"
        "or:\n"
        "  uv run --with opencv-python --with numpy python visualize.py"
    ) from exc


INPUT_CSV = Path("data.csv")
OUTPUT_MP4 = Path("nbody_animation.mp4")

FPS = 30
TRAIL_LENGTH = 24
FRAME_WIDTH = 900
FRAME_HEIGHT = 900
PADDING_PX = 42

# Camera behavior.
CAMERA_SMOOTHING = 0.08        # center smoothing; lower = smoother but more lag
ZOOM_SMOOTHING = 0.06          # zoom smoothing; lower = smoother but more lag
TARGET_MARGIN_FRAC = 0.28      # soft desired margin around all bodies
CONTAIN_MARGIN_FRAC = 0.10     # hard margin guaranteed to stay in frame
MIN_SPAN = 120.0               # avoids over-zoom when bodies are close

# OpenCV uses BGR.
BODY_COLORS_BGR = [
    (0, 215, 255),   # gold
    (255, 144, 30),
    (0, 69, 255),
    (50, 205, 50),
    (214, 112, 218),
    (209, 206, 0),
    (180, 105, 255),
    (47, 255, 173),
]

BG = (25, 15, 11)
GRID = (58, 58, 70)
WHITE = (245, 245, 245)
BLACK = (0, 0, 0)
GOLD = (0, 215, 255)


def parse_int(value: str | None, *, field: str) -> int:
    if value is None or value == "":
        raise ValueError(f"Missing CSV field: {field}")
    return int(value, 0)


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def wide_body_indices(row: dict[str, str]) -> list[int]:
    return sorted(
        int(name[1:])
        for name in row
        if name.startswith("x") and name[1:].isdigit() and f"y{name[1:]}" in row
    )


def rows_to_frames(rows: list[dict[str, str]]) -> list[dict[int, tuple[int, int]]]:
    if not rows:
        return []

    first = rows[0]

    # Format 1: FPGA wide format: step,x0,y0,x1,y1,...
    detected = wide_body_indices(first)
    if detected:
        frames: list[dict[int, tuple[int, int]]] = []
        for row in rows:
            frame: dict[int, tuple[int, int]] = {}
            for body in detected:
                frame[body] = (
                    parse_int(row.get(f"x{body}"), field=f"x{body}"),
                    parse_int(row.get(f"y{body}"), field=f"y{body}"),
                )
            frames.append(frame)
        return frames

    fieldnames = set(first.keys())

    # Format 2: long format with explicit steps: step,body,x,y
    if {"step", "body", "x", "y"}.issubset(fieldnames):
        grouped: dict[int, dict[int, tuple[int, int]]] = {}
        for row in rows:
            step = parse_int(row.get("step"), field="step")
            body = parse_int(row.get("body"), field="body")
            x = parse_int(row.get("x"), field="x")
            y = parse_int(row.get("y"), field="y")
            grouped.setdefault(step, {})[body] = (x, y)
        return [grouped[step] for step in sorted(grouped)]

    # Format 3: single-frame/debug native format: body,x,y
    if {"body", "x", "y"}.issubset(fieldnames):
        frame: dict[int, tuple[int, int]] = {}
        for row in rows:
            body = parse_int(row.get("body"), field="body")
            frame[body] = (
                parse_int(row.get("x"), field="x"),
                parse_int(row.get("y"), field="y"),
            )
        return [frame]

    # Format 4: older native format: body,x,y,new_x,new_y
    if {"body", "new_x", "new_y"}.issubset(fieldnames):
        frame = {}
        for row in rows:
            body = parse_int(row.get("body"), field="body")
            frame[body] = (
                parse_int(row.get("new_x"), field="new_x"),
                parse_int(row.get("new_y"), field="new_y"),
            )
        return [frame]

    raise SystemExit(
        "Unsupported CSV format. Expected one of:\n"
        "  step,x0,y0,x1,y1,...\n"
        "  step,body,x,y\n"
        "  body,x,y\n"
        "  body,x,y,new_x,new_y"
    )


def interpolate_frames(frames: list[dict[int, tuple[int, int]]], factor: int):
    if factor <= 1 or len(frames) < 2:
        return frames

    out = []

    for a, b in zip(frames, frames[1:]):
        out.append(a)

        body_ids = sorted(set(a) | set(b))

        for k in range(1, factor):
            t = k / factor
            mid = {}

            for body in body_ids:
                ax, ay = a.get(body, b[body])
                bx, by = b.get(body, a[body])

                x = int(round(ax + (bx - ax) * t))
                y = int(round(ay + (by - ay) * t))

                mid[body] = (x, y)

            out.append(mid)

    out.append(frames[-1])
    return out


def downsample_frames(
    frames: list[dict[int, tuple[int, int]]],
    *,
    stride: int,
    max_frames: int | None,
) -> tuple[list[dict[int, tuple[int, int]]], int]:
    stride = max(1, stride)

    if max_frames is not None and max_frames > 0 and len(frames) > max_frames:
        stride = max(stride, math.ceil(len(frames) / max_frames))

    sampled = frames[::stride]
    if sampled and sampled[-1] is not frames[-1]:
        sampled.append(frames[-1])

    return sampled, stride


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
                last_x, last_y = 0, 0
            xs.append(last_x)
            ys.append(last_y)

        bodies.append({"idx": body, "xs": xs, "ys": ys})

    return bodies


def all_points_for_frame(bodies: list[dict[str, object]], frame_idx: int) -> tuple[np.ndarray, np.ndarray]:
    xs = np.array([body["xs"][frame_idx] for body in bodies], dtype=np.float64)  # type: ignore[index]
    ys = np.array([body["ys"][frame_idx] for body in bodies], dtype=np.float64)  # type: ignore[index]
    return xs, ys


def smooth_value(old: float | None, new: float, alpha: float) -> float:
    if old is None:
        return new
    alpha = max(0.0, min(1.0, alpha))
    return (1.0 - alpha) * old + alpha * new


def bbox_camera_from_points(
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    aspect: float,
    margin_frac: float,
    min_span: float,
) -> tuple[float, float, float]:
    """Return camera center and span that contains all points plus margin."""
    min_x = float(xs.min())
    max_x = float(xs.max())
    min_y = float(ys.min())
    max_y = float(ys.max())

    cx = 0.5 * (min_x + max_x)
    cy = 0.5 * (min_y + max_y)

    span_x = max(max_x - min_x, min_span)
    span_y = max(max_y - min_y, min_span)

    span_x *= 1.0 + 2.0 * margin_frac
    span_y *= 1.0 + 2.0 * margin_frac

    if span_x / span_y < aspect:
        span_x = span_y * aspect
    else:
        span_y = span_x / aspect

    # Store one canonical span value. For square videos this is exactly the world span.
    span = max(span_x, span_y)
    return cx, cy, span


def camera_to_bounds(cx: float, cy: float, span: float, *, aspect: float) -> tuple[float, float, float, float]:
    if aspect >= 1.0:
        span_x = span
        span_y = span / aspect
    else:
        span_y = span
        span_x = span * aspect

    return (
        cx - 0.5 * span_x,
        cx + 0.5 * span_x,
        cy - 0.5 * span_y,
        cy + 0.5 * span_y,
    )


def clamp_camera_to_contain(
    *,
    cam_cx: float,
    cam_cy: float,
    cam_span: float,
    required_cx: float,
    required_cy: float,
    required_span: float,
    aspect: float,
) -> tuple[float, float, float]:
    """Keep smoothing, but guarantee the current body bbox is inside the frame.

    The smoothed camera may lag behind fast-moving bodies. This function first
    expands the span immediately if needed, then clamps the center just enough
    to contain the current required box.
    """
    cam_span = max(cam_span, required_span)

    cam_min_x, cam_max_x, cam_min_y, cam_max_y = camera_to_bounds(
        cam_cx,
        cam_cy,
        cam_span,
        aspect=aspect,
    )
    req_min_x, req_max_x, req_min_y, req_max_y = camera_to_bounds(
        required_cx,
        required_cy,
        required_span,
        aspect=aspect,
    )

    half_x = 0.5 * (cam_max_x - cam_min_x)
    half_y = 0.5 * (cam_max_y - cam_min_y)

    # For x: center must be in [req_max_x - half_x, req_min_x + half_x].
    low_x = req_max_x - half_x
    high_x = req_min_x + half_x
    if low_x <= high_x:
        cam_cx = min(max(cam_cx, low_x), high_x)
    else:
        # Should only happen from numerical edge cases; fall back to required center.
        cam_cx = required_cx

    # For y: center must be in [req_max_y - half_y, req_min_y + half_y].
    low_y = req_max_y - half_y
    high_y = req_min_y + half_y
    if low_y <= high_y:
        cam_cy = min(max(cam_cy, low_y), high_y)
    else:
        cam_cy = required_cy

    return cam_cx, cam_cy, cam_span


def make_mapper(bounds: tuple[float, float, float, float], *, width: int, height: int, padding_px: int):
    min_x, max_x, min_y, max_y = bounds
    usable_w = max(1, width - 2 * padding_px)
    usable_h = max(1, height - 2 * padding_px)

    def mapper(x: int | float, y: int | float) -> tuple[int, int]:
        px = padding_px + int((float(x) - min_x) * usable_w / max(1e-9, max_x - min_x))
        py = height - padding_px - int((float(y) - min_y) * usable_h / max(1e-9, max_y - min_y))
        return px, py

    return mapper


def draw_grid(img: np.ndarray, *, width: int, height: int, padding_px: int) -> None:
    for t in range(11):
        x = padding_px + int(t * (width - 2 * padding_px) / 10)
        y = padding_px + int(t * (height - 2 * padding_px) / 10)
        cv2.line(img, (x, padding_px), (x, height - padding_px), GRID, 1, cv2.LINE_AA)
        cv2.line(img, (padding_px, y), (width - padding_px, y), GRID, 1, cv2.LINE_AA)


def render_video(
    *,
    frames: list[dict[int, tuple[int, int]]],
    bodies: list[dict[str, object]],
    output_path: Path,
    fps: int,
    trail_length: int,
    width: int,
    height: int,
    padding_px: int,
    camera_smoothing: float,
    zoom_smoothing: float,
    target_margin_frac: float,
    contain_margin_frac: float,
    min_span: float,
    codec: str,
    progress_every: int,
) -> None:
    fourcc = cv2.VideoWriter_fourcc(*codec)
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
    if not writer.isOpened():
        raise SystemExit(
            f"Could not open video writer for {output_path} with codec {codec!r}. "
            "Try --codec mp4v, --codec avc1, or output to .avi with --codec MJPG."
        )

    aspect = width / height
    cam_cx: float | None = None
    cam_cy: float | None = None
    cam_span: float | None = None

    try:
        for frame_idx in range(len(frames)):
            xs, ys = all_points_for_frame(bodies, frame_idx)

            # Soft target: large margin + smoothing for pretty movement.
            target_cx, target_cy, target_span = bbox_camera_from_points(
                xs,
                ys,
                aspect=aspect,
                margin_frac=target_margin_frac,
                min_span=min_span,
            )

            # Hard containment: smaller margin but guaranteed all bodies remain visible.
            req_cx, req_cy, req_span = bbox_camera_from_points(
                xs,
                ys,
                aspect=aspect,
                margin_frac=contain_margin_frac,
                min_span=min_span,
            )

            smoothed_cx = smooth_value(cam_cx, target_cx, camera_smoothing)
            smoothed_cy = smooth_value(cam_cy, target_cy, camera_smoothing)
            smoothed_span = smooth_value(cam_span, target_span, zoom_smoothing)

            cam_cx, cam_cy, cam_span = clamp_camera_to_contain(
                cam_cx=smoothed_cx,
                cam_cy=smoothed_cy,
                cam_span=smoothed_span,
                required_cx=req_cx,
                required_cy=req_cy,
                required_span=req_span,
                aspect=aspect,
            )

            bounds = camera_to_bounds(cam_cx, cam_cy, cam_span, aspect=aspect)
            map_point = make_mapper(bounds, width=width, height=height, padding_px=padding_px)

            img = np.full((height, width, 3), BG, dtype=np.uint8)
            draw_grid(img, width=width, height=height, padding_px=padding_px)

            start = max(0, frame_idx - trail_length)

            # Trails. With a moving camera, very long trails can look like camera streaks,
            # so keep --trail moderate.
            for body_num, body in enumerate(bodies):
                body_idx = int(body["idx"])  # type: ignore[index]
                xs_body = body["xs"]  # type: ignore[index]
                ys_body = body["ys"]  # type: ignore[index]

                color = GOLD if body_idx == 0 else BODY_COLORS_BGR[body_num % len(BODY_COLORS_BGR)]
                prev = None
                for k in range(start, frame_idx + 1):
                    p = map_point(xs_body[k], ys_body[k])
                    if prev is not None:
                        cv2.line(img, prev, p, color, 1, cv2.LINE_AA)
                    prev = p

            # Current body positions.
            for body_num, body in enumerate(bodies):
                body_idx = int(body["idx"])  # type: ignore[index]
                xs_body = body["xs"]  # type: ignore[index]
                ys_body = body["ys"]  # type: ignore[index]
                p = map_point(xs_body[frame_idx], ys_body[frame_idx])

                if body_idx == 0:
                    cv2.circle(img, p, 12, GOLD, 2, cv2.LINE_AA)
                    cv2.circle(img, p, 8, BLACK, -1, cv2.LINE_AA)
                else:
                    color = BODY_COLORS_BGR[body_num % len(BODY_COLORS_BGR)]
                    cv2.circle(img, p, 5, BLACK, -1, cv2.LINE_AA)
                    cv2.circle(img, p, 4, color, -1, cv2.LINE_AA)

            cv2.putText(img, "N-body GPGPU Output", (padding_px, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, WHITE, 1, cv2.LINE_AA)
            cv2.putText(
                img,
                f"frame {frame_idx} / {len(frames) - 1}",
                (padding_px, 55),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                WHITE,
                1,
                cv2.LINE_AA,
            )
            cv2.putText(
                img,
                f"fit-camera  smooth={camera_smoothing:.2f} zoom={zoom_smoothing:.2f}",
                (padding_px, 80),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                WHITE,
                1,
                cv2.LINE_AA,
            )

            writer.write(img)

            if progress_every > 0 and (frame_idx + 1) % progress_every == 0:
                print(f"[INFO] Rendered {frame_idx + 1}/{len(frames)} frames")

    finally:
        writer.release()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render nbody CSV data as an MP4 animation with a smoothed fit camera."
    )
    parser.add_argument("--input", type=Path, default=INPUT_CSV, help="CSV generated by fpga.py or nbody_x86")
    parser.add_argument("--output", type=Path, default=OUTPUT_MP4, help="MP4 file to write")
    parser.add_argument("--fps", type=int, default=FPS, help="Frames per second")
    parser.add_argument("--trail", type=int, default=TRAIL_LENGTH, help="Number of previous frames to show as trail")
    parser.add_argument("--width", type=int, default=FRAME_WIDTH, help="Output video width")
    parser.add_argument("--height", type=int, default=FRAME_HEIGHT, help="Output video height")
    parser.add_argument("--padding-px", type=int, default=PADDING_PX, help="Padding in output pixels")
    parser.add_argument("--stride", type=int, default=1, help="Render only every Nth input frame")
    parser.add_argument("--max-frames", type=int, default=None, help="Downsample to at most this many rendered frames")
    parser.add_argument(
        "--camera-smoothing",
        type=float,
        default=CAMERA_SMOOTHING,
        help="0..1. Lower = smoother but slower camera center response",
    )
    parser.add_argument(
        "--zoom-smoothing",
        type=float,
        default=ZOOM_SMOOTHING,
        help="0..1. Lower = smoother zoom, but the camera expands immediately when needed to contain all bodies",
    )
    parser.add_argument(
        "--target-margin-frac",
        type=float,
        default=TARGET_MARGIN_FRAC,
        help="Soft desired margin around the body bounding box",
    )
    parser.add_argument(
        "--contain-margin-frac",
        type=float,
        default=CONTAIN_MARGIN_FRAC,
        help="Hard guaranteed margin around bodies. Increase if bodies touch frame edges",
    )
    parser.add_argument(
        "--min-span",
        type=float,
        default=MIN_SPAN,
        help="Minimum camera world span to avoid over-zooming",
    )
    parser.add_argument("--codec", default="mp4v", help="OpenCV codec, e.g. mp4v, avc1, MJPG")
    parser.add_argument("--progress-every", type=int, default=200, help="Print progress every N frames; 0 disables")
    parser.add_argument(
        "--slowdown",
        type=int,
        default=1,
        help="Insert interpolated frames between simulation frames. 4 means ~4x slower playback at same FPS.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input.exists():
        raise SystemExit(f"{args.input} not found.")
    if args.fps < 1:
        raise SystemExit("--fps must be >= 1")
    if args.trail < 0:
        raise SystemExit("--trail must be >= 0")
    if args.width < 64 or args.height < 64:
        raise SystemExit("--width and --height must be >= 64")
    if args.padding_px < 0:
        raise SystemExit("--padding-px must be >= 0")
    if args.stride < 1:
        raise SystemExit("--stride must be >= 1")
    if not (0.0 <= args.camera_smoothing <= 1.0):
        raise SystemExit("--camera-smoothing must be in [0, 1]")
    if not (0.0 <= args.zoom_smoothing <= 1.0):
        raise SystemExit("--zoom-smoothing must be in [0, 1]")
    if args.target_margin_frac < 0.0:
        raise SystemExit("--target-margin-frac must be >= 0")
    if args.contain_margin_frac < 0.0:
        raise SystemExit("--contain-margin-frac must be >= 0")
    if args.min_span <= 0:
        raise SystemExit("--min-span must be > 0")

    rows = load_rows(args.input)
    if not rows:
        raise SystemExit(f"{args.input} is empty.")

    frames = rows_to_frames(rows)
    if not frames:
        raise SystemExit(f"{args.input} did not contain any frames.")

    frames = interpolate_frames(frames, args.slowdown)

    original_frames = len(frames)
    frames, used_stride = downsample_frames(
        frames,
        stride=args.stride,
        max_frames=args.max_frames,
    )

    bodies = frames_to_bodies(frames)
    if not bodies:
        raise SystemExit(f"{args.input} did not contain any bodies.")

    print(
        f"[INFO] Rendering {len(frames)} frames from {original_frames} input frames "
        f"(stride={used_stride}, fps={args.fps})"
    )

    render_video(
        frames=frames,
        bodies=bodies,
        output_path=args.output,
        fps=args.fps,
        trail_length=args.trail,
        width=args.width,
        height=args.height,
        padding_px=args.padding_px,
        camera_smoothing=args.camera_smoothing,
        zoom_smoothing=args.zoom_smoothing,
        target_margin_frac=args.target_margin_frac,
        contain_margin_frac=args.contain_margin_frac,
        min_span=args.min_span,
        codec=args.codec,
        progress_every=args.progress_every,
    )

    print(f"[SUCCESS] Wrote {args.output} with {len(bodies)} bodies and {len(frames)} rendered frames")


if __name__ == "__main__":
    main()
