"""Embed native PDF fonts and provide vector SVG / 600dpi PNG companions."""
from __future__ import annotations

import argparse
from pathlib import Path

from scripts.research.task010.audit import OUT, write_json
from scripts.research.task010.qa_pdf import POPPLER, TEX, command, parse


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native",type=Path,required=True)
    args=parser.parse_args()
    root=args.native.resolve()
    if not root.is_relative_to(OUT):
        parser.error("Native render must be in TASK-010")
    records=[]
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        name=folder.name
        source=folder/f"{name}.pdf"
        if not source.exists():
            continue
        pdf=folder/f"{name}_embedded.pdf"
        if pdf.exists():
            raise FileExistsError(pdf)
        command([str(TEX/"rungs.exe"),"-q","-dBATCH","-dNOPAUSE","-sDEVICE=pdfwrite",
                 "-dPDFSETTINGS=/prepress","-dEmbedAllFonts=true","-dSubsetFonts=true",
                 "-sFONTPATH=C:/Windows/Fonts","-sOutputFile="+str(pdf),str(source)])
        qa=folder/"pdf_qa"
        qa.mkdir()
        parsed=parse(pdf,qa)
        command([str(TEX/"pdftocairo.exe"),"-svg",str(pdf),str(folder/f"{name}.svg")])
        command([str(POPPLER/"pdftoppm.exe"),"-r","600","-png","-singlefile",
                 str(pdf),str(folder/name)])
        records.append(dict(id=name,**parsed,editable_project=f"{name}.opju",
            svg_text="glyph paths from vector PDF; native editable text and curves in OPJU"))
    write_json(root/"publication_manifest.json",records)


if __name__=="__main__":
    main()
