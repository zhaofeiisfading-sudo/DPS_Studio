from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def slide_number(path: Path) -> int:
    match = re.search(r"(\d+)", path.stem)
    if match is None:
        raise ValueError(f"Missing slide number in {path.name}")
    return int(match.group(1))


def main() -> None:
    source_dir = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    paths = sorted(source_dir.glob("*.PNG"), key=slide_number)
    if len(paths) != 15:
        raise RuntimeError(f"Expected 15 PNG files, found {len(paths)}")

    columns = 3
    rows = 5
    thumb_width = 640
    thumb_height = 360
    label_height = 32
    margin = 16
    canvas = Image.new(
        "RGB",
        (
            columns * thumb_width + (columns + 1) * margin,
            rows * (thumb_height + label_height) + (rows + 1) * margin,
        ),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    for index, path in enumerate(paths):
        image = Image.open(path).convert("RGB")
        image.thumbnail((thumb_width, thumb_height), Image.Resampling.LANCZOS)
        x = margin + (index % columns) * (thumb_width + margin)
        y = margin + (index // columns) * (thumb_height + label_height + margin)
        canvas.paste(image, (x, y))
        draw.text((x, y + thumb_height + 8), f"Slide {index + 1}", fill="black", font=font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=92)


if __name__ == "__main__":
    main()
