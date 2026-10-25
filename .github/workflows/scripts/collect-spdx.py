#!/usr/bin/env python3
"""Retain the self-contained SPDX 3 image document produced by Yocto."""
import argparse
import gzip
import json
from pathlib import Path
import shutil


def collect(deploy: Path, image: str, output: Path) -> None:
    candidates = [deploy / f"{image}{suffix}.spdx.json" for suffix in ("", ".rootfs")]
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        raise ValueError(f"Missing image SPDX document: {candidates}")

    # Image documents include the package, file and license graph. Copying only
    # a recipe document would lose the installed image's dependency inventory.
    with source.open() as stream:
        document = json.load(stream)
    graph = document.get("@graph", [])
    types = {element.get("type") for element in graph}
    if not {"SpdxDocument", "software_Sbom", "software_Package"} <= types:
        raise ValueError(f"Not a self-contained SPDX 3 image document: {source}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as stream, output.open("wb") as compressed:
        with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as archive:
            shutil.copyfileobj(stream, archive)
    print(f"SPDX SBOM: {source} -> {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deploy", type=Path)
    parser.add_argument("image")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    collect(args.deploy, args.image, args.output)


if __name__ == "__main__":
    main()
