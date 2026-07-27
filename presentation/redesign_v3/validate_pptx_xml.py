from __future__ import annotations

import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree


def main() -> None:
    path = Path(sys.argv[1])
    needles = (b"undefined", b"NaN", b"Infinity", b'prst=""', b'type=""')
    findings: list[tuple[str, str]] = []
    parse_errors: list[tuple[str, str]] = []
    shapes: Counter[str] = Counter()
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            data = archive.read(name)
            for needle in needles:
                if needle in data:
                    findings.append((name, needle.decode("ascii")))
            if name.endswith((".xml", ".rels")):
                try:
                    root = ElementTree.fromstring(data)
                except ElementTree.ParseError as error:
                    parse_errors.append((name, str(error)))
                    continue
                for element in root.iter():
                    preset = element.attrib.get("prst")
                    if preset is not None:
                        shapes[preset] += 1
    print("findings", findings)
    print("parse_errors", parse_errors)
    print("preset_shapes", shapes.most_common())


if __name__ == "__main__":
    main()
