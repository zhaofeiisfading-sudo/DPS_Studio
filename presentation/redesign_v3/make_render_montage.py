from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parent
RENDERS = ROOT / "rendered_slides"
QA = ROOT / "_qa_tmp"


def natural_key(path: Path) -> list[int | str]:
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", path.name)
    ]


def font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/msyh.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def make_montage(
    images: list[Path], output: Path, columns: int, cell_width: int = 840
) -> None:
    thumb_height = round(cell_width * 9 / 16)
    label_height = 42
    rows = (len(images) + columns - 1) // columns
    canvas = Image.new(
        "RGB", (columns * cell_width, rows * (thumb_height + label_height)), "#dedad4"
    )
    draw = ImageDraw.Draw(canvas)
    label_font = font(24)
    for index, path in enumerate(images):
        row = index // columns
        column = index % columns
        x = column * cell_width
        y = row * (thumb_height + label_height)
        with Image.open(path) as source:
            preview = ImageOps.fit(
                source.convert("RGB"),
                (cell_width, thumb_height),
                Image.Resampling.LANCZOS,
            )
        canvas.paste(preview, (x, y))
        draw.rectangle(
            (x, y + thumb_height, x + cell_width, y + thumb_height + label_height),
            fill="#f7f2ea",
        )
        draw.text(
            (x + 14, y + thumb_height + 7),
            f"Slide {index + 1:02d}",
            fill="#292623",
            font=label_font,
        )
    canvas.save(output, quality=92)


def main() -> None:
    QA.mkdir(parents=True, exist_ok=True)
    images = sorted(RENDERS.glob("*.PNG"), key=natural_key)
    if len(images) != 18:
        raise RuntimeError(f"Expected 18 rendered slides, found {len(images)}")
    tag = sys.argv[1] if len(sys.argv) > 1 else "v1"
    make_montage(images, QA / f"montage_{tag}.png", columns=3, cell_width=840)
    make_montage(
        images[:9], QA / f"montage_{tag}_01_09.png", columns=2, cell_width=1120
    )
    make_montage(
        images[9:], QA / f"montage_{tag}_10_18.png", columns=2, cell_width=1120
    )
    print(QA / f"montage_{tag}.png")


if __name__ == "__main__":
    main()
