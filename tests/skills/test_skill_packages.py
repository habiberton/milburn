from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from milburn.domain import Role
from milburn.validation.skill_validation import validate_skill_package


ROOT = Path(__file__).parents[2]
SKILLS = ROOT / ".agents/skills"
EXPECTED = {
    "milburn-coordination",
    "milburn-planning",
    "milburn-routing",
    "milburn-architecture",
    "milburn-long-running-coder",
    "milburn-qa",
}


def test_exact_required_skill_suite_is_structurally_valid() -> None:
    observed = {path.name for path in SKILLS.iterdir() if path.is_dir()}
    assert observed == EXPECTED

    validated = [validate_skill_package(SKILLS, name) for name in sorted(EXPECTED)]
    assert {item.manifest.name for item in validated} == EXPECTED
    assert all(item.root_digest for item in validated)


def test_role_and_policy_configs_are_json_compatible_yaml() -> None:
    roles = json.loads((ROOT / "config/roles.yaml").read_text(encoding="utf-8"))["roles"]
    policies = json.loads((ROOT / "config/policies.yaml").read_text(encoding="utf-8"))["roles"]

    assert set(roles) == {role.value for role in Role}
    assert set(policies) == set(roles)
    assert {skill for entry in roles.values() for skill in entry["required_skills"]} == EXPECTED


def test_architecture_validator_accepts_reviewable_markdown(tmp_path: Path) -> None:
    artifact = tmp_path / "PRD.md"
    artifact.write_text("# Product\n\n" + "Observable requirement. " * 8, encoding="utf-8")
    script = SKILLS / "milburn-architecture/scripts/validate-specs.py"

    completed = subprocess.run(
        [sys.executable, str(script), str(artifact)], capture_output=True, text=True
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_architecture_validator_rejects_unreviewable_markdown(tmp_path: Path) -> None:
    artifact = tmp_path / "PRD.md"
    artifact.write_text("too short", encoding="utf-8")
    script = SKILLS / "milburn-architecture/scripts/validate-specs.py"

    completed = subprocess.run(
        [sys.executable, str(script), str(artifact)], capture_output=True, text=True
    )

    assert completed.returncode == 1
    assert "missing top-level heading" in completed.stdout


def test_coder_handoff_validator_rejects_missing_public_evidence(tmp_path: Path) -> None:
    manifest = tmp_path / "handoff.json"
    manifest.write_text(json.dumps({"task_id": "MB-007"}), encoding="utf-8")
    script = SKILLS / "milburn-long-running-coder/scripts/verify-handoff.py"

    completed = subprocess.run(
        [sys.executable, str(script), str(manifest)], capture_output=True, text=True
    )

    assert completed.returncode == 1
    assert "public contract" in completed.stdout


def test_coder_handoff_validator_accepts_complete_public_evidence(tmp_path: Path) -> None:
    manifest = tmp_path / "handoff.json"
    manifest.write_text(
        json.dumps(
            {
                "task_id": "MB-007",
                "attempt_id": "a01",
                "worktree": "/tmp/worktree",
                "branch": "bootstrap/builder/MB-007/a01",
                "base_sha": "abcdef0",
                "head_sha": "abcdef1",
                "progress": "bootstrap/progress/tasks/MB-007.md",
                "tests": ["20 passed"],
                "remaining": ["coordinator review"],
            }
        ),
        encoding="utf-8",
    )
    script = SKILLS / "milburn-long-running-coder/scripts/verify-handoff.py"

    completed = subprocess.run(
        [sys.executable, str(script), str(manifest)], capture_output=True, text=True
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_qa_validator_prevents_pass_with_blocking_finding(tmp_path: Path) -> None:
    report = tmp_path / "qa.json"
    report.write_text(
        json.dumps(
            {
                "task_id": "MB-007",
                "attempt_id": "a01",
                "candidate_sha": "abcdef0",
                "acceptance": ["mapped"],
                "tests": ["passed"],
                "findings": [{"severity": "blocking"}],
                "risks": [],
                "outcome": "passed",
            }
        ),
        encoding="utf-8",
    )
    script = SKILLS / "milburn-qa/scripts/validate-qa-report.py"

    completed = subprocess.run(
        [sys.executable, str(script), str(report)], capture_output=True, text=True
    )

    assert completed.returncode == 1
    assert "blocking finding" in completed.stdout


def test_qa_validator_accepts_complete_nonblocking_report(tmp_path: Path) -> None:
    report = tmp_path / "qa.json"
    report.write_text(
        json.dumps(
            {
                "task_id": "MB-007",
                "attempt_id": "a01",
                "candidate_sha": "abcdef0",
                "acceptance": ["all mapped"],
                "tests": ["passed"],
                "findings": [],
                "risks": [],
                "outcome": "passed",
            }
        ),
        encoding="utf-8",
    )
    script = SKILLS / "milburn-qa/scripts/validate-qa-report.py"

    completed = subprocess.run(
        [sys.executable, str(script), str(report)], capture_output=True, text=True
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
