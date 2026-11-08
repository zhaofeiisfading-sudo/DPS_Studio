"""Parse PDFs before review, verify vectors/fonts, then render QA PNGs."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from scripts.research.task010.audit import OUT, write_json

TEX = Path("D:/texlive/2026/bin/windows")
POPPLER = Path("C:/Users/89484/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin")


def command(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", check=True)
    return result.stdout + result.stderr


def parse(path: Path, output: Path) -> dict[str, Any]:
    bbox = output / "text_bbox.html"
    command([str(TEX/"pdftotext.exe"), "-bbox-layout", str(path), str(bbox)])
    pages: list[dict[str, Any]] = []
    for element in ET.parse(bbox).getroot().iter():
        if element.tag.rsplit("}", 1)[-1] == "page":
            words = [dict(text=w.text, **w.attrib) for w in element.iter()
                     if w.tag.rsplit("}", 1)[-1] == "word"]
            pages.append(dict(page_number=len(pages)+1, **element.attrib, words=words))
    fonts = command([str(TEX/"pdffonts.exe"), str(path)])
    images = command([str(TEX/"pdfimages.exe"), "-list", str(path)])
    info = command([str(TEX/"pdfinfo.exe"), str(path)])
    outside = []
    for page in pages:
        for word in page["words"]:
            if (float(word["xMin"]) < -.5 or float(word["yMin"]) < -.5 or
                float(word["xMax"]) > float(page["width"])+.5 or
                    float(word["yMax"]) > float(page["height"])+.5):
                outside.append(word)
    font_lines = [line for line in fonts.splitlines()[2:] if line.strip()]
    all_embedded = all(re.search(r"\s+yes\s+(?:yes|no)\s+(?:yes|no)\s+\d+\s+\d+", line)
                       is not None for line in font_lines)
    image_count = len([line for line in images.splitlines() if re.match(r"\s*\d+\s+\d+\s+",line)])
    result: dict[str, Any] = dict(source=str(path), pages=pages, fonts=fonts, images=images,
        pdfinfo=info, all_fonts_embedded=all_embedded, raster_image_objects=image_count,
        text_outside_page=outside, parse_before_visual_review=True,
        extraction_limitations="Standalone figures: section/paragraph/table structures do not apply; captions and exact source tables are separate sidecars. Formula symbols may be split into text runs.")
    write_json(output/"pdf_parsed.json", result)
    command([str(POPPLER/"pdftoppm.exe"), "-r", "180", "-png", "-singlefile",
             str(path), str(output/"rendered_page")])
    return dict(file=path.name, pages=len(pages), words=sum(len(p["words"]) for p in pages),
                fonts_embedded=all_embedded, image_objects=image_count, outside_words=len(outside))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(OUT):
        parser.error("Use a new TASK-010 subdirectory")
    output.mkdir(parents=True, exist_ok=False)
    paths = sorted(args.figures.glob("Fig*.pdf"))
    if args.native:
        paths += sorted(args.native.glob("*/*_embedded.pdf"))
    rows = []
    for path in paths:
        directory=output/path.stem
        directory.mkdir()
        rows.append(parse(path,directory))
    write_json(output/"qa_summary.json",rows)
    print(json.dumps(rows,ensure_ascii=False))
    if not all(r["pages"]==1 and r["words"]>5 and r["fonts_embedded"] and
               r["image_objects"]==0 and r["outside_words"]==0 for r in rows):
        raise AssertionError("PDF QA failed; inspect parsed evidence and renderings")


if __name__ == "__main__":
    main()
