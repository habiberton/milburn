from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil

import pytest

from milburn.validation.skill_validation import (
    DIGEST_RE,
    SkillFailureCode,
    SkillValidationError,
    parse_skill_manifest,
    validate_skill_package,
)


FIXTURES = Path(__file__).parents[2] / "fixtures" / "skills"


def test_valid_fixture_produces_stable_root_and_resource_digests() -> None:
    first = validate_skill_package(FIXTURES / "valid", "milburn-fixture")
    second = validate_skill_package(FIXTURES / "valid", "milburn-fixture")

    assert first == second
    assert first.manifest.version == "1.2.3"
    assert DIGEST_RE.fullmatch(first.root_digest)
    assert first.resource_digests == (
        sha256(
            (FIXTURES / "valid/milburn-fixture/references/guide.md").read_bytes()
        ).hexdigest(),
    )


def test_declared_missing_resource_is_an_explicit_missing_failure() -> None:
    with pytest.raises(SkillValidationError) as raised:
        validate_skill_package(FIXTURES / "missing-reference", "milburn-fixture")

    assert raised.value.code is SkillFailureCode.MISSING
    assert "references/absent.md" in raised.value.detail


@pytest.mark.parametrize(
    "content, detail",
    [
        ("# no frontmatter", "start with frontmatter"),
        (
            "---\nname: milburn-example\nversion: latest\ndescription: x\n"
            "resources: []\nscripts: []\n---\nbody\n",
            "semantic",
        ),
        (
            "---\nname: milburn-example\nversion: 1.0.0\ndescription: x\n"
            "resources: [\"../escape.md\"]\nscripts: []\n---\nbody\n",
            "invalid references path",
        ),
    ],
)
def test_malformed_frontmatter_fails_closed(content: str, detail: str) -> None:
    with pytest.raises(SkillValidationError, match=detail):
        parse_skill_manifest(content, "milburn-example")


def test_unreferenced_files_and_placeholders_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    shutil.copytree(FIXTURES / "valid", root)
    skill = root / "milburn-fixture"
    (skill / "extra.md").write_text("unreferenced", encoding="utf-8")

    with pytest.raises(SkillValidationError, match="unreferenced"):
        validate_skill_package(root, "milburn-fixture")

    (skill / "extra.md").unlink()
    (skill / "references/guide.md").write_text("TODO later", encoding="utf-8")
    with pytest.raises(SkillValidationError, match="unfinished placeholder"):
        validate_skill_package(root, "milburn-fixture")


def test_declared_script_must_be_executable(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill = root / "milburn-scripted"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: milburn-scripted\nversion: 1.0.0\ndescription: scripted\n"
        'resources: []\nscripts: ["scripts/check.py"]\n---\nbody\n',
        encoding="utf-8",
    )
    (skill / "scripts/check.py").write_text("print('ok')\n", encoding="utf-8")

    with pytest.raises(SkillValidationError, match="not executable"):
        validate_skill_package(root, "milburn-scripted")


def test_symlink_cannot_escape_package(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    shutil.copytree(FIXTURES / "valid", root)
    guide = root / "milburn-fixture/references/guide.md"
    guide.unlink()
    guide.symlink_to(tmp_path / "outside.md")

    with pytest.raises(SkillValidationError, match="must not be a symlink"):
        validate_skill_package(root, "milburn-fixture")
