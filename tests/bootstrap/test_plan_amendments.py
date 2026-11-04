from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bootstrap.amendments.validate import preflight_errors, validate_records


VALID_RECORD = """# AMEND-001 — Example amendment

## Authority

- Source: direct user instruction.
- Authorized task: MB-022 / GitHub issue #27.

## Requested change

Change the task graph.

## Affected tasks

- Added MB-022.

## Active-work impact

No active work changed ownership.

## Registry and specification changes

- Registry changes: add MB-022.
- Specification changes: record the dispatch gate.
- GitHub changes: add issue dependency links.

## Effectiveness

- Planning commit: `0123456789abcdef`
- Effective remote PR: #28
- Effective merge commit: `fedcba9876543210`
- Dispatch status: resumed after read-back.
- Resolution status: effective and reconciled
"""


class PlanAmendmentBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "bootstrap" / "amendments").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_record(self, content: str = VALID_RECORD) -> None:
        (self.root / "bootstrap" / "amendments" / "AMEND-001.md").write_text(
            content, encoding="utf-8"
        )

    def test_complete_effective_record_is_valid(self) -> None:
        self.write_record()
        self.assertEqual(validate_records(self.root), [])
        self.assertEqual(preflight_errors(self.root, dirty_paths=()), [])

    def test_missing_required_record_section_fails(self) -> None:
        self.write_record(VALID_RECORD.replace("## Active-work impact", "## Notes"))
        self.assertTrue(
            any("Active-work impact" in error for error in validate_records(self.root))
        )

    def test_unresolved_amendment_blocks_preflight(self) -> None:
        self.write_record(
            VALID_RECORD.replace(
                "Resolution status: effective and reconciled",
                "Resolution status: pending impact assessment",
            )
        )
        self.assertTrue(
            any(
                "unresolved amendment blocks dispatch" in error
                for error in preflight_errors(self.root, dirty_paths=())
            )
        )

    def test_dirty_planning_file_blocks_preflight(self) -> None:
        self.write_record()
        errors = preflight_errors(
            self.root, dirty_paths=("bootstrap/tasks.json", "PRD.md")
        )
        self.assertTrue(any("PRD.md, bootstrap/tasks.json" in error for error in errors))

    def test_invalid_commit_or_pr_evidence_fails(self) -> None:
        self.write_record(
            VALID_RECORD.replace("`0123456789abcdef`", "not-a-commit").replace(
                "#28", "missing"
            )
        )
        errors = validate_records(self.root)
        self.assertTrue(any("Planning commit" in error for error in errors))
        self.assertTrue(any("Effective remote PR" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
