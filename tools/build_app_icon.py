"""Rebuild the supplied PDV icon locally; never change the input PNG.

Requires Pillow, NumPy and SciPy already present in the development environment.
This cleanup is for the audited rounded-square artwork, not arbitrary artwork.
The source histogram's bulk starts above 240 (peaks 252/253); edge samples
show real coverage within two pixels of that core, then alpha 1..15 residue.
Thresholds are explicit arguments so a different source must be audited again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage


ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def inspect_alpha(image: Image.Image) -> dict:
    rgba = np.asarray(image.convert("RGBA"))
    alpha = rgba[..., 3]
    return {
        "mode": image.mode,
        "size": list(image.size),
        "has_alpha": "A" in image.getbands(),
        "corners": [rgba[y, x].tolist() for y, x in [(0, 0), (0, -1), (-1, 0), (-1, -1)]],
        "alpha_min": int(alpha.min()),
        "alpha_max": int(alpha.max()),
        "alpha_histogram": np.bincount(alpha.ravel(), minlength=256).tolist(),
        "transparent": int((alpha == 0).sum()),
        "partial": int(((alpha > 0) & (alpha < 255)).sum()),
        "opaque": int((alpha == 255).sum()),
        "bbox": image.convert("RGBA").getbbox(),
    }


def clean_alpha(
    image: Image.Image, *, core_alpha: int = 240, edge_width: float = 2.0
) -> tuple[Image.Image, dict]:
    """Preserve the measured silhouette, opaque RGB and its narrow AA band."""
    rgba = np.array(image.convert("RGBA"))
    alpha = rgba[..., 3]
    labels, count = ndimage.label(alpha >= core_alpha)
    if count == 0:
        raise ValueError("No opaque body found; audit this source before cleanup.")
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    core = ndimage.binary_fill_holes(labels == sizes.argmax())
    distance, indices = ndimage.distance_transform_edt(~core, return_indices=True)
    edge = (~core) & (distance <= edge_width) & (alpha > 0)
    removed = (~core) & (~edge) & (alpha > 0)
    result = rgba.copy()
    result[~(core | edge)] = 0
    result[core, 3] = 255
    # Retain fractional coverage; compensate for the source's 252/253 body opacity.
    body_alpha = float(np.median(alpha[core]))
    result[edge, 3] = np.clip(np.rint(alpha[edge] * (255.0 / body_alpha)), 1, 254)
    # Unassociated edge RGB can be badly quantized or pale. Extend the nearest
    # body colour without altering ANY RGB within the measured solid body.
    nearest = rgba[tuple(indices)]
    result[edge, :3] = nearest[edge, :3]
    rgb = rgba[edge, :3].astype(float)
    report = {
        "core_alpha": core_alpha,
        "edge_width_source_pixels": edge_width,
        "body_alpha_median": body_alpha,
        "removed_pixels": int(removed.sum()),
        "removed_alpha_max": int(alpha[removed].max()) if removed.any() else 0,
        "retained_aa_pixels": int(edge.sum()),
        "body_pixels": int(core.sum()),
        "body_rgb_unchanged": bool(np.array_equal(result[core, :3], rgba[core, :3])),
        "pale_neutral_edge_pixels": int(
            ((np.ptp(rgb, axis=1) < 20) & (rgb.mean(axis=1) > 150)).sum()
        ),
    }
    return Image.fromarray(result), report


def resize_icon(image: Image.Image, size: int) -> Image.Image:
    """Premultiplied Lanczos; suppress ringing outside actual silhouette support."""
    resized = image.convert("RGBa").resize((size, size), Image.Resampling.LANCZOS)
    rgba = np.array(resized.convert("RGBA"))
    support = np.asarray(image.getchannel("A").resize((size, size), Image.Resampling.BOX))
    rgba[(support == 0) | (rgba[..., 3] == 0)] = 0
    # Fully covered footprint must not become translucent from Lanczos ringing.
    rgba[support == 255, 3] = 255
    return Image.fromarray(rgba)


def write_ico(image: Image.Image, destination: Path) -> None:
    frames = [resize_icon(image, size) for size in ICON_SIZES]
    frames[-1].save(
        destination, format="ICO", sizes=[(s, s) for s in ICON_SIZES],
        append_images=frames[:-1],
    )


def build(source: Path, output: Path, diagnostics: Path, **options: object) -> dict:
    targets = [output / "pdv_studio_master.png", output / "pdv_studio.ico"]
    if any(p.exists() for p in targets) or diagnostics.exists():
        raise FileExistsError("Use new output paths; existing assets/diagnostics are protected.")
    with Image.open(source) as original:
        original.load()
        cleaned, cleanup = clean_alpha(original, **options)
        report = {
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "original": inspect_alpha(original),
            "cleanup": cleanup,
            "cleaned": inspect_alpha(cleaned),
            "ico_sizes": list(ICON_SIZES),
        }
        output.mkdir(parents=True, exist_ok=True)
        diagnostics.mkdir(parents=True)
        cleaned.save(targets[0])
        write_ico(cleaned, targets[1])
        backgrounds = {"white": "white", "black": "black", "gray": "#d0d0d0"}
        for name, icon in [("original", original), ("cleaned", cleaned)]:
            for label, color in backgrounds.items():
                background = Image.new("RGBA", icon.size, color)
                Image.alpha_composite(background, icon).convert("RGB").save(
                    diagnostics / f"{name}_on_{label}.png"
                )
        sheet = Image.new("RGB", (1000, 660), "#808080")
        draw = ImageDraw.Draw(sheet)
        with Image.open(targets[1]) as ico:
            report["ico_verified_sizes"] = sorted(s[0] for s in ico.ico.sizes())
            for row, (label, color) in enumerate(backgrounds.items()):
                draw.rectangle((0, row * 220, 999, row * 220 + 219), fill=color)
                draw.text((8, row * 220 + 6), label, fill="gray")
                x = 15
                for size in (16, 32, 48, 64, 128, 256):
                    frame = ico.ico.getimage((size, size)).convert("RGBA")
                    display = frame if size <= 128 else resize_icon(frame, 170)
                    sheet.paste(display, (x, row * 220 + 28), display)
                    draw.text((x, row * 220 + 203), f"{size}px", fill="gray")
                    x += max(display.width + 25, 100)
        sheet.save(diagnostics / "ico_contact_sheet.png")
    (diagnostics / "alpha_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--core-alpha", type=int, default=240)
    parser.add_argument("--edge-width", type=float, default=2.0)
    args = parser.parse_args()
    if not 1 <= args.core_alpha <= 255 or args.edge_width <= 0:
        parser.error("core-alpha must be 1..255; edge-width must be positive")
    report = build(
        args.source, args.output, args.diagnostics,
        core_alpha=args.core_alpha, edge_width=args.edge_width,
    )
    print(json.dumps(report["cleanup"], indent=2))


if __name__ == "__main__":
    main()
