"""Assemble checked native projects, embed PDF fonts and create vector SVGs.

This is a local Research artifact assembly, not a Production promotion.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from artifacts.research_clean_task9.prepare_figures import T9, source

TEX = Path("D:/texlive/2026/bin/windows")
PPM = Path("C:/Users/89484/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe")


def command(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    return result.stdout + result.stderr


def parse_pdf(path: Path, output: Path) -> dict[str, Any]:
    bbox_path = output / "pdf_text_bbox.html"
    command([str(TEX / "pdftotext.exe"), "-bbox", str(path), str(bbox_path)])
    xml = ET.parse(bbox_path)
    pages = []
    for page in xml.getroot().iter():
        if page.tag.rsplit("}", 1)[-1] != "page":
            continue
        words = [dict(text=w.text, **w.attrib) for w in page.iter() if w.tag.rsplit("}", 1)[-1] == "word"]
        pages.append(dict(**page.attrib, words=words))
    font_report = command([str(TEX / "pdffonts.exe"), str(path)])
    images_report = command([str(TEX / "pdfimages.exe"), "-list", str(path)])
    info = command([str(TEX / "pdfinfo.exe"), str(path)])
    result = dict(pages=pages, fonts=font_report, images=images_report, pdfinfo=info,
                  parse_before_visual_review=True, source=source(path))
    (output / "pdf_parsed.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def assemble(data: Path, native: Path, supplements: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    records = []
    for identifier in manifest["figures"]:
        folder = output / identifier
        shutil.copytree(data / identifier, folder)
        render = native / identifier
        project = render / f"{identifier}.opju"
        raw_pdf = render / f"{identifier}.pdf"
        shutil.copy2(project, folder / project.name)
        shutil.copy2(render / "origin_log.json", folder / "origin_log.json")
        shutil.copytree(render / "native_data", folder / "native_data")
        pdf = folder / raw_pdf.name
        # Origin 2021 leaves fonts unembedded. Ghostscript resolves installed
        # Times New Roman, embeds subsets, and retains vectors and page size.
        command([str(TEX / "rungs.exe"), "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
                 "-dPDFSETTINGS=/prepress", "-dEmbedAllFonts=true", "-dSubsetFonts=true",
                 "-sFONTPATH=C:/Windows/Fonts", "-sOutputFile=" + str(pdf), str(raw_pdf)])
        command([str(TEX / "pdftocairo.exe"), "-svg", str(pdf), str(folder / f"{identifier}.svg")])
        parsed = parse_pdf(pdf, folder)
        command([str(PPM), "-r", "600", "-png", "-singlefile", str(pdf), str(folder / identifier)])
        records.append(dict(id=identifier, backend="Origin 2021 native", native_project=source(project),
                            raw_native_pdf=source(raw_pdf), publication_pdf=source(pdf),
                            pages=len(parsed["pages"]), raster_dpi=600,
                            svg="vector PDF conversion; glyph paths; edit text/curves in OPJU",
                            fonts_embedded=True))
        print(f"Assembled {identifier}", flush=True)
    for original in sorted(supplements.iterdir()):
        if not original.is_dir():
            continue
        folder = output / original.name
        shutil.copytree(original, folder)
        parsed = parse_pdf(folder / f"{original.name}.pdf", folder)
        records.append(dict(id=original.name, backend="Matplotlib", pages=len(parsed["pages"]),
                            publication_pdf=source(folder / f"{original.name}.pdf"), raster_dpi=600,
                            native_project=None, fonts_embedded=True))
    (output / "publication_manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--supplements", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(T9):
        parser.error("Output must be a new TASK-009 directory")
    assemble(args.data.resolve(), args.native.resolve(), args.supplements.resolve(), output)


if __name__ == "__main__":
    main()
