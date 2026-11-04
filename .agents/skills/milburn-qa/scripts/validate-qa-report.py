#!/usr/bin/env python3
"""Validate the bounded public fields of a QA report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED = {"task_id", "attempt_id", "candidate_sha", "acceptance", "tests", "findings", "risks", "outcome"}
OUTCOMES = {"passed", "changes_requested", "decision_needed", "failed"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    args = parser.parse_args()
    try:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(error)
        return 1
    if not isinstance(report, dict) or set(report) != REQUIRED:
        print("QA report fields do not match the public contract")
        return 1
    if any(
        not isinstance(report[field], str) or not report[field].strip()
        for field in ("task_id", "attempt_id", "candidate_sha", "outcome")
    ):
        print("QA report identifiers and outcome must be non-empty strings")
        return 1
    if report["outcome"] not in OUTCOMES:
        print("QA report outcome is unknown")
        return 1
    if any(not isinstance(report[field], list) for field in ("acceptance", "tests", "findings", "risks")):
        print("QA report evidence fields must be lists")
        return 1
    if not report["acceptance"] or not report["tests"]:
        print("QA report requires acceptance and test evidence")
        return 1
    if any(not isinstance(finding, dict) for finding in report["findings"]):
        print("QA report findings must be objects")
        return 1
    if report["outcome"] == "passed" and any(
        finding.get("severity") == "blocking" for finding in report["findings"]
    ):
        print("QA report cannot pass with a blocking finding")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
