#!/usr/bin/env python3
"""Validate the public shape of a transcript-free Coder handoff."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED = {"task_id", "attempt_id", "worktree", "branch", "base_sha", "head_sha", "progress", "tests", "remaining"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    args = parser.parse_args()
    try:
        payload = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(error)
        return 1
    if not isinstance(payload, dict) or set(payload) != REQUIRED:
        print("handoff fields do not match the public contract")
        return 1
    text_fields = {"task_id", "attempt_id", "worktree", "branch", "base_sha", "head_sha", "progress"}
    if any(not isinstance(payload[field], str) or not payload[field].strip() for field in text_fields):
        print("handoff fields must be explicit and non-empty")
        return 1
    if any(not isinstance(payload[field], list) or not payload[field] for field in ("tests", "remaining")):
        print("handoff tests and remaining work must be non-empty lists")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
