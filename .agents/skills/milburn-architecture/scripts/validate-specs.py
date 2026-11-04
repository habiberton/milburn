#!/usr/bin/env python3
"""Validate bounded Markdown specification artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    errors: list[str] = []
    for raw in args.paths:
        path = Path(raw)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            errors.append(f"{path}: {error}")
            continue
        if not text.startswith("# "):
            errors.append(f"{path}: missing top-level heading")
        if len(text.strip()) < 80:
            errors.append(f"{path}: artifact is too small to be reviewable")
    if errors:
        for error in errors:
            print(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
