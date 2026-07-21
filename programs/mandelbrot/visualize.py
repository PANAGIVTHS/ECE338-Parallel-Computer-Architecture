import argparse
import csv
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError as exc:
    uv = shutil.which("uv")
    if uv is not None and os.environ.get("MANDELBROT_VISUALIZE_UV_REEXEC") != "1":
        env = os.environ.copy()
        env["MANDELBROT_VISUALIZE_UV_REEXEC"] = "1"
        cmd = [
            uv,
            "run",
            "--with",
            "opencv-python-headless",
            "--with",
            "numpy",
            "python",
            str(Path(__file__).resolve()),
            *sys.argv[1:],
        ]
        raise SystemExit(subprocess.run(cmd, cwd=Path(__file__).resolve().parent, env=env).returncode)

    raise SystemExit(
        "visualize.py needs OpenCV and NumPy.\n"
        "Install them with:\n"
        "  pip install opencv-python-headless numpy\n"
        "or:\n"
        "  uv run --with opencv-python-headless --with numpy python visualize.py"
    ) from exc


INPUT_CSV = Path("data.csv")
OUTPUT_MP4 = Path("mandelbrot_zoom.mp4")
OUTPUT_LAST = Path("mandelbrot_last.png")

DEFAULT_WIDTH = 64
DEFAULT_HEIGHT = 64
DEFAULT_MAX_ITER = 64
DEFAULT_FPS = 30
DEFAULT_SCALE = 10


def parse_int(value: str | None, *, field: str) -> int:
    if value is None or value == "":
        raise ValueError(f"Missing CSV field: {field}")
    return int(value, 0)


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def detect_pixel_columns(row: dict[str, str], width: int) -> list[str]:
    """Detect pixel columns for one row of the Mandelbrot image.

    Preferred format:
        frame,row,p0,p1,...,p63

    Also accepted:
        frame,row,x0,x1,...,x63
        frame,row,v0,v1,...,v63
    """
    for prefix in ("p", "x", "v"):
        cols = [f"{prefix}{i}" for i in range(width)]
        if all(col in row for col in cols):
            return cols

    # Fallback: use all numeric-looking columns except metadata.
    metadata = {
        "frame",
        "frame_idx",
        "zoom_frame",
        "row",
        "y",
        "step",
        "scale",
        "scale_q",
        "center_re",
        "center_re_q",
        "center_im",
        "center_im_q",
    }
    candidates = [name for name in row.keys() if name not in metadata]
    if len(candidates) >= width:
        return candidates[:width]

    raise SystemExit(
        "Could not detect Mandelbrot pixel columns. Expected columns like:\n"
        "  frame,row,p0,p1,...,p63\n"
        "or:\n"
        "  frame,row,x0,x1,...,x63"
    )


def assemble_frames(
    rows: list[dict[str, str]],
    *,
    width: int,
    height: int,
) -> tuple[list[np.ndarray], list[int]]:
    """Assemble CSV rows into image frames.

    Expected CSV shape:
        frame,row,p0,p1,...,p63

    Each CSV row is one Mandelbrot image row produced by one kernel launch.
    64 rows form one 64x64 zoom frame.
    """
    if not rows:
        return [], []

    pixel_cols = detect_pixel_columns(rows[0], width)

    grouped: dict[int, dict[int, list[int]]] = {}

    for implicit_index, row in enumerate(rows):
        frame = int(row.get("frame", row.get("frame_idx", row.get("zoom_frame", "0"))))
        y = int(row.get("row", row.get("y", str(implicit_index % height))))

        pixels = [parse_int(row.get(col), field=col) for col in pixel_cols[:width]]

        if not (0 <= y < height):
            raise SystemExit(f"Invalid row index {y}; expected 0..{height - 1}")

        grouped.setdefault(frame, {})[y] = pixels

    images: list[np.ndarray] = []
    frame_numbers: list[int] = []

    for frame in sorted(grouped):
        rows_for_frame = grouped[frame]

        if len(rows_for_frame) != height:
            missing = [y for y in range(height) if y not in rows_for_frame]
            raise SystemExit(
                f"Frame {frame} has {len(rows_for_frame)} rows, expected {height}. "
                f"Missing rows: {missing[:10]}{'...' if len(missing) > 10 else ''}"
            )

        img = np.zeros((height, width), dtype=np.int32)
        for y in range(height):
            img[y, :] = np.array(rows_for_frame[y], dtype=np.int32)

        images.append(img)
        frame_numbers.append(frame)

    return images, frame_numbers


def downsample_frames(
    frames: list[np.ndarray],
    frame_numbers: list[int],
    *,
    stride: int,
    max_frames: int | None,
) -> tuple[list[np.ndarray], list[int], int]:
    stride = max(1, stride)

    if max_frames is not None and max_frames > 0 and len(frames) > max_frames:
        stride = max(stride, math.ceil(len(frames) / max_frames))

    sampled_frames = frames[::stride]
    sampled_numbers = frame_numbers[::stride]

    if sampled_frames and sampled_frames[-1] is not frames[-1]:
        sampled_frames.append(frames[-1])
        sampled_numbers.append(frame_numbers[-1])

    return sampled_frames, sampled_numbers, stride


def iterations_to_bgr(iter_img: np.ndarray, *, max_iter: int, colormap: int, invert: bool) -> np.ndarray:
    """Convert iteration counts to a BGR color image."""
    clipped = np.clip(iter_img, 0, max_iter).astype(np.int32)

    # Points that did not escape are black.
    inside = clipped >= max_iter

    if invert:
        norm = ((max_iter - clipped) * 255) // max(1, max_iter)
    else:
        norm = (clipped * 255) // max(1, max_iter)

    norm = norm.astype(np.uint8)
    color = cv2.applyColorMap(norm, colormap)
    color[inside] = (0, 0, 0)

    return color


def open_video_writer(path: Path, *, width: int, height: int, fps: int, codec: str) -> cv2.VideoWriter:
    fourcc = cv2.VideoWriter_fourcc(*codec)
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))

    if not writer.isOpened():
        raise SystemExit(
            f"Could not open video writer for {path} with codec {codec!r}.\n"
            "Try --codec mp4v, --codec avc1, or output to .avi with --codec MJPG."
        )

    return writer


def render_video(
    *,
    frames: list[np.ndarray],
    frame_numbers: list[int],
    output: Path,
    last_png: Path | None,
    fps: int,
    max_iter: int,
    scale: int,
    codec: str,
    colormap_name: str,
    invert: bool,
    interpolation: str,
    progress_every: int,
) -> None:
    if not frames:
        raise SystemExit("No frames to render.")

    colormap = getattr(cv2, f"COLORMAP_{colormap_name.upper()}", None)
    if colormap is None:
        available = [
            name.removeprefix("COLORMAP_").lower()
            for name in dir(cv2)
            if name.startswith("COLORMAP_")
        ]
        raise SystemExit(
            f"Unknown colormap {colormap_name!r}. Examples: "
            f"{', '.join(sorted(available)[:12])}"
        )

    if interpolation == "nearest":
        interp = cv2.INTER_NEAREST
    elif interpolation == "linear":
        interp = cv2.INTER_LINEAR
    elif interpolation == "cubic":
        interp = cv2.INTER_CUBIC
    else:
        raise SystemExit("--interpolation must be one of: nearest, linear, cubic")

    h, w = frames[0].shape
    out_w = w * scale
    out_h = h * scale

    writer = open_video_writer(output, width=out_w, height=out_h, fps=fps, codec=codec)

    try:
        for idx, iter_img in enumerate(frames):
            bgr = iterations_to_bgr(iter_img, max_iter=max_iter, colormap=colormap, invert=invert)
            bgr = cv2.resize(bgr, (out_w, out_h), interpolation=interp)

            cv2.putText(
                bgr,
                f"frame {frame_numbers[idx]} | {idx + 1}/{len(frames)}",
                (12, 26),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

            writer.write(bgr)

            if progress_every > 0 and (idx + 1) % progress_every == 0:
                print(f"[INFO] Rendered {idx + 1}/{len(frames)} frames")

        if last_png is not None:
            last = iterations_to_bgr(frames[-1], max_iter=max_iter, colormap=colormap, invert=invert)
            last = cv2.resize(last, (out_w, out_h), interpolation=interp)
            cv2.imwrite(str(last_png), last)

    finally:
        writer.release()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Mandelbrot CSV rows as an MP4 zoom animation.")
    parser.add_argument("--input", type=Path, default=INPUT_CSV, help="CSV generated by mandelbrot fpga.py")
    parser.add_argument("--output", type=Path, default=OUTPUT_MP4, help="MP4 file to write")
    parser.add_argument("--last-png", type=Path, default=OUTPUT_LAST, help="Also write the final frame as PNG; use empty string to disable")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="Mandelbrot image width")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="Mandelbrot image height")
    parser.add_argument("--max-iter", type=int, default=DEFAULT_MAX_ITER, help="MAX_ITER used by the C kernel")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help="Video frames per second")
    parser.add_argument("--scale", type=int, default=DEFAULT_SCALE, help="Pixel scale factor, e.g. 64x64 with --scale 10 -> 640x640")
    parser.add_argument("--stride", type=int, default=1, help="Render only every Nth zoom frame")
    parser.add_argument("--max-frames", type=int, default=None, help="Downsample to at most this many video frames")
    parser.add_argument("--codec", default="mp4v", help="OpenCV fourcc codec, e.g. mp4v, avc1, MJPG")
    parser.add_argument("--colormap", default="turbo", help="OpenCV colormap name, e.g. turbo, inferno, plasma, hot, jet")
    parser.add_argument("--invert", action="store_true", help="Invert color mapping")
    parser.add_argument("--interpolation", choices=["nearest", "linear", "cubic"], default="nearest")
    parser.add_argument("--progress-every", type=int, default=50, help="Print progress every N frames; 0 disables")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.width < 1 or args.height < 1:
        raise SystemExit("--width and --height must be positive")
    if args.max_iter < 1:
        raise SystemExit("--max-iter must be positive")
    if args.fps < 1:
        raise SystemExit("--fps must be positive")
    if args.scale < 1:
        raise SystemExit("--scale must be positive")
    if args.stride < 1:
        raise SystemExit("--stride must be >= 1")
    if not args.input.exists():
        raise SystemExit(f"{args.input} not found.")

    last_png: Path | None = args.last_png
    if str(args.last_png) == "":
        last_png = None

    rows = load_rows(args.input)
    if not rows:
        raise SystemExit(f"{args.input} is empty.")

    frames, frame_numbers = assemble_frames(rows, width=args.width, height=args.height)
    original_count = len(frames)

    frames, frame_numbers, used_stride = downsample_frames(
        frames,
        frame_numbers,
        stride=args.stride,
        max_frames=args.max_frames,
    )

    print(
        f"[INFO] Rendering {len(frames)} frames from {original_count} input zoom frames "
        f"(stride={used_stride}, fps={args.fps}, scale={args.scale})"
    )

    render_video(
        frames=frames,
        frame_numbers=frame_numbers,
        output=args.output,
        last_png=last_png,
        fps=args.fps,
        max_iter=args.max_iter,
        scale=args.scale,
        codec=args.codec,
        colormap_name=args.colormap,
        invert=args.invert,
        interpolation=args.interpolation,
        progress_every=args.progress_every,
    )

    print(f"[SUCCESS] Wrote {args.output}")
    if last_png is not None:
        print(f"[SUCCESS] Wrote {last_png}")


if __name__ == "__main__":
    main()
