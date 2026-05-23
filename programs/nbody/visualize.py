import csv
from pathlib import Path

INPUT_CSV = Path("simulation_data.csv")
OUTPUT_SVG = Path("nbody_trajectories.svg")
WIDTH = 900
HEIGHT = 900
PADDING = 70
TRAIL_COLORS = ["#FFD700", "#1E90FF", "#FF4500"]
BODY_NAMES = ["body 0", "body 1", "body 2"]


def load_rows(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def collect_points(rows):
    bodies = []
    for idx in range(3):
        points = []
        for row in rows:
            points.append((int(row[f"x{idx}"]), int(row[f"y{idx}"])))
        bodies.append(points)
    return bodies


def scale_points(bodies):
    xs = [x for body in bodies for x, _ in body]
    ys = [y for body in bodies for _, y in body]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    if min_x == max_x:
        max_x = min_x + 1
    if min_y == max_y:
        max_y = min_y + 1

    plot_w = WIDTH - 2 * PADDING
    plot_h = HEIGHT - 2 * PADDING

    def scale(point):
        x, y = point
        sx = PADDING + (x - min_x) * plot_w // (max_x - min_x)
        sy = HEIGHT - PADDING - (y - min_y) * plot_h // (max_y - min_y)
        return sx, sy

    return [[scale(point) for point in body] for body in bodies], (min_x, max_x, min_y, max_y)


def polyline(points):
    return " ".join(f"{x},{y}" for x, y in points)


def write_svg(path, bodies, bounds, rows):
    min_x, max_x, min_y, max_y = bounds
    parts = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">')
    parts.append('<rect width="100%" height="100%" fill="#0b0f19"/>')
    parts.append(f'<rect x="{PADDING}" y="{PADDING}" width="{WIDTH - 2 * PADDING}" height="{HEIGHT - 2 * PADDING}" fill="none" stroke="#9aa4b2" stroke-width="1"/>')
    parts.append('<text x="450" y="35" text-anchor="middle" fill="white" font-family="monospace" font-size="24">N-body GPU Program Preview</text>')
    parts.append(f'<text x="450" y="62" text-anchor="middle" fill="#9aa4b2" font-family="monospace" font-size="13">steps={len(rows)} x=[{min_x},{max_x}] y=[{min_y},{max_y}]</text>')

    for idx, points in enumerate(bodies):
        color = TRAIL_COLORS[idx]
        parts.append(f'<polyline points="{polyline(points)}" fill="none" stroke="{color}" stroke-width="3" stroke-opacity="0.78"/>')
        start_x, start_y = points[0]
        end_x, end_y = points[-1]
        parts.append(f'<circle cx="{start_x}" cy="{start_y}" r="6" fill="none" stroke="{color}" stroke-width="2"/>')
        parts.append(f'<circle cx="{end_x}" cy="{end_y}" r="10" fill="{color}" stroke="black" stroke-width="2"/>')
        parts.append(f'<text x="{end_x + 12}" y="{end_y - 12}" fill="{color}" font-family="monospace" font-size="14">{BODY_NAMES[idx]}</text>')

    parts.append('<text x="70" y="850" fill="#9aa4b2" font-family="monospace" font-size="13">hollow circle = start, filled circle = final position</text>')
    parts.append('</svg>')
    path.write_text("\n".join(parts) + "\n")


def main():
    if not INPUT_CSV.exists():
        raise SystemExit("simulation_data.csv not found. Run ./nbody_x86 > simulation_data.csv first.")

    rows = load_rows(INPUT_CSV)
    if not rows:
        raise SystemExit("simulation_data.csv is empty.")

    bodies = collect_points(rows)
    scaled, bounds = scale_points(bodies)
    write_svg(OUTPUT_SVG, scaled, bounds, rows)
    print(f"Wrote {OUTPUT_SVG}")


if __name__ == "__main__":
    main()
