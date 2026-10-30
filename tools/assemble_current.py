#!/usr/bin/env python3
"""Reconstruct one verified ZIP from immutable transport parts in the release PR.

The script neither extracts nor changes game configuration records.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
from zipfile import ZipFile


def assemble(parts_dir: Path, output: Path, digest: str, expected_bytes: int,
             expected_files: int, expected_parts: int = 33) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Expected SHA-256 must have 64 hex digits")
    if expected_bytes <= 0 or expected_files <= 0 or expected_parts <= 0:
        raise ValueError("Invalid expected size, file count or part count")
    if not parts_dir.is_dir() or parts_dir.is_symlink():
        raise ValueError("Missing or unsafe parts directory")
    parts = sorted(parts_dir.iterdir())
    names = [f"part-{i:03d}.bin" for i in range(expected_parts)]
    if [p.name for p in parts] != names:
        raise ValueError("Transfer part sequence missing, extra or incorrectly named")
    if any(not p.is_file() or p.is_symlink() for p in parts):
        raise ValueError("Non-file or symlink transfer part")
    if output.resolve().is_relative_to(parts_dir.resolve()):
        raise ValueError("Output cannot be inside source parts directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".assembling")
    try:
        sha = hashlib.sha256()
        total = 0
        with temporary.open("wb") as dest:
            for part in parts:
                with part.open("rb") as src:
                    while block := src.read(1024 * 1024):
                        dest.write(block)
                        sha.update(block)
                        total += len(block)
        if total != expected_bytes or sha.hexdigest() != digest:
            raise ValueError("Assembled data does not match the source ZIP size / SHA-256")
        with ZipFile(temporary) as archive:
            files = [f for f in archive.infolist() if not f.is_dir()]
            if len(files) != expected_files or len({f.filename for f in files}) != expected_files:
                raise ValueError("ZIP file count or file names mismatch")
            if archive.testzip() is not None:
                raise ValueError("ZIP CRC validation failed")
        temporary.replace(output)
        return {"size": total, "sha256": digest, "files": len(files), "parts": len(parts)}
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parts", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--size", type=int, required=True)
    p.add_argument("--files", type=int, required=True)
    p.add_argument("--count", type=int, default=33)
    a = p.parse_args()
    print(assemble(a.parts, a.output, a.sha256, a.size, a.files, a.count))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
