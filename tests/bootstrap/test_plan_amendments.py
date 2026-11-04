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

- No active work.

## Registry and specification changes

- Registry changes: add MB-022.
- Specification changes: record the dispatch gate.
- GitHub changes: add issue dependency links.

## Effectiveness

- Planning commit: `0123456789abcdef`
- Effective remote PR: #28
- Effective merge commit: `fedcba9876543210`
- Dispatch status: resumed
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

    def test_checked_in_amendment_records_clear_semantic_preflight(self) -> None:
        repository = Path(__file__).resolve().parents[2]

        self.assertEqual(preflight_errors(repository, dirty_paths=()), [])

    def test_missing_required_record_section_fails(self) -> None:
        self.write_record(VALID_RECORD.replace("## Active-work impact", "## Notes"))
        self.assertTrue(
            any("Active-work impact" in error for error in validate_records(self.root))
        )

    def test_required_evidence_sections_cannot_be_empty(self) -> None:
        for content, expected in (
            (
                VALID_RECORD.replace("\nChange the task graph.\n", "\n"),
                "Requested change section must be nonempty",
            ),
            (
                VALID_RECORD.replace("\n- Added MB-022.\n", "\n"),
                "Affected tasks section must be nonempty",
            ),
            (
                VALID_RECORD.replace("\n- No active work.\n", "\n"),
                "Active-work impact requires",
            ),
        ):
            with self.subTest(expected=expected):
                self.write_record(content)
                self.assertTrue(
                    any(expected in error for error in validate_records(self.root))
                )

    def test_unrelated_heading_cannot_supply_empty_required_section(self) -> None:
        disguised_empty = VALID_RECORD.replace(
            "Change the task graph.", "## Unrelated notes\n\nLooks nonempty elsewhere."
        )
        self.write_record(disguised_empty)

        self.assertTrue(
            any(
                "Requested change section must be nonempty" in error
                for error in validate_records(self.root)
            )
        )

    def test_active_work_requires_known_classification_or_explicit_none(self) -> None:
        impact = """| Work | Classification | Decision |
|---|---|---|
| MB-005/a01 | keep-going-ish | Continue. |"""
        self.write_record(VALID_RECORD.replace("- No active work.", impact))

        self.assertTrue(
            any(
                "unknown active-work classification" in error
                for error in validate_records(self.root)
            )
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

    def test_well_formed_pending_record_validates_but_keeps_dispatch_frozen(self) -> None:
        pending = (
            VALID_RECORD.replace("`0123456789abcdef`", "pending")
            .replace("#28", "pending")
            .replace("`fedcba9876543210`", "pending")
            .replace("Dispatch status: resumed", "Dispatch status: frozen")
            .replace(
                "Resolution status: effective and reconciled",
                "Resolution status: pending",
            )
        )
        self.write_record(pending)

        self.assertEqual(validate_records(self.root), [])
        self.assertTrue(
            any(
                "unresolved amendment blocks dispatch" in error
                for error in preflight_errors(self.root, dirty_paths=())
            )
        )

    def test_effective_record_with_frozen_dispatch_still_blocks_preflight(self) -> None:
        self.write_record(
            VALID_RECORD.replace("Dispatch status: resumed", "Dispatch status: frozen")
        )

        self.assertEqual(validate_records(self.root), [])
        self.assertTrue(
            any(
                "record still freezes dispatch" in error
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

    def test_pull_request_reference_must_match_completely(self) -> None:
        self.write_record(VALID_RECORD.replace("#28", "#28garbage"))
        self.assertTrue(
            any("exactly identify" in error for error in validate_records(self.root))
        )

    def test_dispatch_and_resolution_states_are_closed_and_consistent(self) -> None:
        self.write_record(VALID_RECORD.replace("Dispatch status: resumed", "Dispatch status: maybe"))
        self.assertTrue(
            any("invalid Dispatch status" in error for error in validate_records(self.root))
        )

        pending_but_resumed = VALID_RECORD.replace(
            "Resolution status: effective and reconciled",
            "Resolution status: pending",
        )
        self.write_record(pending_but_resumed)
        errors = validate_records(self.root)
        self.assertTrue(any("pending amendment must freeze dispatch" in error for error in errors))

    def test_invalid_superficially_effective_record_does_not_clear_preflight(self) -> None:
        invalid = VALID_RECORD.replace("#28", "#28garbage").replace(
            "Dispatch status: resumed", "Dispatch status: nonsense"
        )
        self.write_record(invalid)

        errors = preflight_errors(self.root, dirty_paths=())
        self.assertTrue(any("Effective remote PR" in error for error in errors))
        self.assertTrue(any("invalid Dispatch status" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
