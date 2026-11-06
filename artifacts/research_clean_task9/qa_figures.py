"""Structural QA and review contact sheets; never alter publication figures."""
from __future__ import annotations

import json
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from artifacts.research_clean_task9.prepare_figures import T9


def main() -> None:
    figures = T9 / "figures_final"
    output = T9 / "checks/figure_qa_final"
    output.mkdir(parents=True, exist_ok=False)
    items = json.loads((figures / "publication_manifest.json").read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for item in items:
        folder = figures / item["id"]
        spec = json.loads((folder / "figure.json").read_text(encoding="utf-8"))
        pdf = json.loads((folder / "pdf_parsed.json").read_text(encoding="utf-8"))
        outside_page = []
        for page in pdf["pages"]:
            for word in page["words"]:
                if (float(word["xMin"]) < -0.5 or float(word["yMin"]) < -0.5
                    or float(word["xMax"]) > float(page["width"]) + 0.5
                    or float(word["yMax"]) > float(page["height"]) + 0.5):
                    outside_page.append(word)
        cropped: list[dict[str, Any]] = []
        for pi, panel in enumerate(spec.get("panels", []), 1):
            for s in panel["series"]:
                y = np.asarray(s["y"], dtype=float)
                if panel.get("ylim"):
                    count = int(np.count_nonzero(np.isfinite(y) & ((y < panel["ylim"][0]) | (y > panel["ylim"][1]))))
                    if count:
                        cropped.append(dict(panel=pi, series=s["data_csv"], count=count,
                            interpretation="intentional local zoom" if pi == 2 and item["id"] in (
                                "Fig05_Acceleration", "Fig06_Clutter", "Fig07_DoubleShockFailure") else "REVIEW"))
        records.append(dict(id=item["id"], outside_page_words=outside_page,
                            out_of_y_range=cropped, font_report=pdf["fonts"],
                            image_report=pdf["images"]))
    for offset in range(0, len(items), 6):
        subset = items[offset:offset + 6]
        fig, axes = plt.subplots(3, 2, figsize=(14, 15))
        for ax in axes.ravel():
            ax.axis("off")
        for ax, item in zip(axes.ravel(), subset, strict=False):
            path = figures / item["id"] / f"{item['id']}.png"
            with Image.open(path) as im:
                im.thumbnail((1200, 1000))
                ax.imshow(np.asarray(im))
            ax.set_title(item["id"], fontsize=11)
        fig.tight_layout()
        fig.savefig(output / f"contact_{offset // 6 + 1:02d}.png", dpi=150)
        plt.close(fig)
    (output / "structural_qa.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([dict(id=r["id"], out_of_page=len(r["outside_page_words"]),
                           unexplained_y_cropping=[x for x in r["out_of_y_range"] if x["interpretation"] == "REVIEW"])
                      for r in records], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
