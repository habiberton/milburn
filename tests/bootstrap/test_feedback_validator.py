from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bootstrap.feedback.validate import validate


VALID_ENTRY = """# MB-001 feedback brief

## Findings

### MB-001-F001

- Discovery phase: review
- Severity: meaningful
- Symptom: An invalid candidate behavior was observed.
- Root cause: The public guard admitted an invalid value.
- Resolution: The guard now rejects the invalid value.
- Fix commit: 0123456789abcdef
- Regression evidence: `python3 -m unittest tests.test_guard` — 1 passed.
- Lesson: Validate authority at the public boundary.
- Status: resolved
- Attempt: a01
- Worker candidate: fedcba9876543210
- Coordinator integration: 1234567890abcdef
- GitHub PR: #18
- Linked issue: unavailable — resolved within originating task.
"""


class FeedbackValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "bootstrap" / "feedback").mkdir(parents=True)
        (self.root / "bootstrap" / "tasks.json").write_text(
            json.dumps({"tasks": [{"id": "MB-001"}, {"id": "MB-002"}]}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_brief(self, name: str, content: str = VALID_ENTRY) -> None:
        (self.root / "bootstrap" / "feedback" / name).write_text(
            content, encoding="utf-8"
        )

    def test_accepts_valid_resolved_entry(self) -> None:
        self.write_brief("MB-001.md")
        self.assertEqual(validate(self.root), [])

    def test_rejects_invalid_filename(self) -> None:
        self.write_brief("mb-001.md")
        self.assertTrue(any("invalid brief filename" in error for error in validate(self.root)))

    def test_rejects_missing_required_headings(self) -> None:
        self.write_brief("MB-001.md", VALID_ENTRY.replace("## Findings", "## Notes"))
        self.assertTrue(any("required headings" in error for error in validate(self.root)))

    def test_rejects_zero_feedback_sequence(self) -> None:
        self.write_brief("MB-001.md", VALID_ENTRY.replace("MB-001-F001", "MB-001-F000"))
        self.assertTrue(any("feedback ID must match" in error for error in validate(self.root)))

    def test_rejects_unknown_task_id(self) -> None:
        self.write_brief("MB-999.md", VALID_ENTRY.replace("MB-001", "MB-999"))
        self.assertTrue(any("unknown task ID" in error for error in validate(self.root)))

    def test_rejects_duplicate_feedback_ids(self) -> None:
        duplicate = VALID_ENTRY + "\n".join(VALID_ENTRY.splitlines()[4:]) + "\n"
        self.write_brief("MB-001.md", duplicate)
        self.assertTrue(any("duplicate feedback ID" in error for error in validate(self.root)))

    def test_resolved_entry_requires_fix_commit(self) -> None:
        self.write_brief(
            "MB-001.md",
            VALID_ENTRY.replace(
                "- Fix commit: 0123456789abcdef",
                "- Fix commit: unavailable — not recorded",
            ),
        )
        self.assertTrue(any("requires a fix commit" in error for error in validate(self.root)))

    def test_resolved_entry_requires_regression_command_and_result(self) -> None:
        self.write_brief(
            "MB-001.md",
            VALID_ENTRY.replace(
                "- Regression evidence: `python3 -m unittest tests.test_guard` — 1 passed.",
                "- Regression evidence: unavailable — not recorded",
            ),
        )
        self.assertTrue(any("requires regression command" in error for error in validate(self.root)))


if __name__ == "__main__":
    unittest.main()
