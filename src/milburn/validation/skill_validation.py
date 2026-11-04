"""Strict structural validation for local Codex skill packages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import stat


SKILL_NAME_RE = re.compile(r"^milburn-[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION_RE = re.compile(r"^[1-9]\d*\.\d+\.\d+$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD|FIXME|PLACEHOLDER)\b", re.IGNORECASE)
_REQUIRED_FIELDS = ("name", "version", "description", "resources", "scripts")


class SkillFailureCode(StrEnum):
    MISSING = "missing"
    MALFORMED = "malformed"
    CHANGED = "changed"


class SkillValidationError(ValueError):
    """One launch-blocking skill validation failure."""

    def __init__(self, code: SkillFailureCode, skill_name: str, detail: str) -> None:
        super().__init__(f"{skill_name}: {detail}")
        self.code = code
        self.skill_name = skill_name
        self.detail = detail


@dataclass(frozen=True, slots=True)
class SkillManifest:
    name: str
    version: str
    description: str
    resources: tuple[str, ...]
    scripts: tuple[str, ...]

    @property
    def referenced_paths(self) -> tuple[str, ...]:
        return (*self.resources, *self.scripts)


@dataclass(frozen=True, slots=True)
class ValidatedSkill:
    manifest: SkillManifest
    skill_path: Path
    root_digest: str
    resource_digests: tuple[str, ...]


def validate_skill_package(skills_root: Path, skill_name: str) -> ValidatedSkill:
    """Validate one package and return stable content evidence."""

    if not SKILL_NAME_RE.fullmatch(skill_name):
        raise SkillValidationError(
            SkillFailureCode.MALFORMED, skill_name, "invalid skill name"
        )
    lexical_root = skills_root.absolute()
    if lexical_root.is_symlink():
        raise SkillValidationError(
            SkillFailureCode.MALFORMED,
            skill_name,
            "skills root must not be a symlink",
        )
    root = lexical_root.resolve()
    skill_path = root / skill_name
    if not skill_path.is_dir():
        raise SkillValidationError(
            SkillFailureCode.MISSING, skill_name, "skill directory is missing"
        )
    if skill_path.is_symlink():
        raise SkillValidationError(
            SkillFailureCode.MALFORMED, skill_name, "skill directory must not be a symlink"
        )
    manifest_path = skill_path / "SKILL.md"
    if not manifest_path.is_file():
        raise SkillValidationError(
            SkillFailureCode.MISSING, skill_name, "SKILL.md is missing"
        )
    if _has_symlink_component(skill_path, manifest_path):
        raise SkillValidationError(
            SkillFailureCode.MALFORMED,
            skill_name,
            "SKILL.md or one of its ancestors is a symlink",
        )
    manifest = parse_skill_manifest(manifest_path.read_text(encoding="utf-8"), skill_name)
    if manifest.name != skill_name:
        raise SkillValidationError(
            SkillFailureCode.MALFORMED,
            skill_name,
            f"frontmatter name {manifest.name!r} does not match directory",
        )

    expected = {"SKILL.md", *manifest.referenced_paths}
    observed: set[str] = set()
    for path in skill_path.rglob("*"):
        relative = path.relative_to(skill_path).as_posix()
        if path.is_symlink():
            raise SkillValidationError(
                SkillFailureCode.MALFORMED,
                skill_name,
                f"package path {relative!r} must not be a symlink",
            )
        if path.is_dir():
            continue
        observed.add(relative)
    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    if missing:
        raise SkillValidationError(
            SkillFailureCode.MISSING,
            skill_name,
            f"referenced files are missing: {', '.join(missing)}",
        )
    if extra:
        raise SkillValidationError(
            SkillFailureCode.MALFORMED,
            skill_name,
            f"unreferenced package files are not allowed: {', '.join(extra)}",
        )

    file_bytes: dict[str, bytes] = {}
    for relative in sorted(expected):
        path = skill_path / relative
        if _has_symlink_component(skill_path, path):
            raise SkillValidationError(
                SkillFailureCode.MALFORMED,
                skill_name,
                f"package path {relative!r} has a symlinked ancestor",
            )
        try:
            path.resolve(strict=True).relative_to(skill_path.resolve(strict=True))
        except (OSError, ValueError) as error:
            raise SkillValidationError(
                SkillFailureCode.MALFORMED,
                skill_name,
                f"package path {relative!r} escapes the approved skill root",
            ) from error
        data = path.read_bytes()
        file_bytes[relative] = data
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SkillValidationError(
                SkillFailureCode.MALFORMED,
                skill_name,
                f"{relative!r} must be UTF-8 text",
            ) from error
        if _PLACEHOLDER_RE.search(text):
            raise SkillValidationError(
                SkillFailureCode.MALFORMED,
                skill_name,
                f"{relative!r} contains an unfinished placeholder",
            )
    for relative in manifest.scripts:
        mode = (skill_path / relative).stat().st_mode
        if not mode & stat.S_IXUSR:
            raise SkillValidationError(
                SkillFailureCode.MALFORMED,
                skill_name,
                f"script {relative!r} is not executable",
            )

    resource_digests = tuple(
        sha256(file_bytes[relative]).hexdigest()
        for relative in manifest.referenced_paths
    )
    root_digest = _root_digest(file_bytes)
    return ValidatedSkill(manifest, skill_path.resolve(), root_digest, resource_digests)


def parse_skill_manifest(content: str, skill_name: str = "<unknown>") -> SkillManifest:
    """Parse the deliberately small, deterministic frontmatter subset."""

    lines = content.splitlines()
    if not lines or lines[0] != "---":
        raise SkillValidationError(
            SkillFailureCode.MALFORMED, skill_name, "SKILL.md must start with frontmatter"
        )
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise SkillValidationError(
            SkillFailureCode.MALFORMED, skill_name, "frontmatter is not closed"
        ) from error
    if not any(line.strip() for line in lines[end + 1 :]):
        raise SkillValidationError(
            SkillFailureCode.MALFORMED, skill_name, "SKILL.md instructions are empty"
        )

    values: dict[str, object] = {}
    for line in lines[1:end]:
        if not line or line.startswith((" ", "\t")) or ":" not in line:
            raise SkillValidationError(
                SkillFailureCode.MALFORMED,
                skill_name,
                f"invalid frontmatter line {line!r}",
            )
        key, raw = line.split(":", 1)
        if key in values:
            raise SkillValidationError(
                SkillFailureCode.MALFORMED, skill_name, f"duplicate field {key!r}"
            )
        if key not in _REQUIRED_FIELDS:
            raise SkillValidationError(
                SkillFailureCode.MALFORMED, skill_name, f"unknown field {key!r}"
            )
        raw = raw.strip()
        if key in {"resources", "scripts"}:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as error:
                raise SkillValidationError(
                    SkillFailureCode.MALFORMED,
                    skill_name,
                    f"{key} must be a JSON string list",
                ) from error
            if not isinstance(parsed, list) or any(
                not isinstance(item, str) for item in parsed
            ):
                raise SkillValidationError(
                    SkillFailureCode.MALFORMED,
                    skill_name,
                    f"{key} must be a JSON string list",
                )
            values[key] = tuple(parsed)
        else:
            values[key] = raw
    missing = set(_REQUIRED_FIELDS) - values.keys()
    if missing:
        raise SkillValidationError(
            SkillFailureCode.MALFORMED,
            skill_name,
            f"missing frontmatter fields: {', '.join(sorted(missing))}",
        )

    name = values["name"]
    version = values["version"]
    description = values["description"]
    resources = values["resources"]
    scripts = values["scripts"]
    assert isinstance(name, str) and isinstance(version, str)
    assert isinstance(description, str) and isinstance(resources, tuple)
    assert isinstance(scripts, tuple)
    if not SKILL_NAME_RE.fullmatch(name):
        raise SkillValidationError(
            SkillFailureCode.MALFORMED, skill_name, "frontmatter name is invalid"
        )
    if not VERSION_RE.fullmatch(version):
        raise SkillValidationError(
            SkillFailureCode.MALFORMED, skill_name, "version must be semantic x.y.z"
        )
    if not description.strip():
        raise SkillValidationError(
            SkillFailureCode.MALFORMED, skill_name, "description must be non-empty"
        )
    paths = (*resources, *scripts)
    if len(paths) != len(set(paths)):
        raise SkillValidationError(
            SkillFailureCode.MALFORMED, skill_name, "referenced paths must be unique"
        )
    for relative in resources:
        _validate_relative_path(relative, "references", skill_name)
    for relative in scripts:
        _validate_relative_path(relative, "scripts", skill_name)
    return SkillManifest(name, version, description, resources, scripts)


def _validate_relative_path(relative: str, required_parent: str, skill_name: str) -> None:
    path = PurePosixPath(relative)
    if (
        not relative
        or path.is_absolute()
        or ".." in path.parts
        or path.parts[0] != required_parent
        or len(path.parts) < 2
    ):
        raise SkillValidationError(
            SkillFailureCode.MALFORMED,
            skill_name,
            f"invalid {required_parent} path {relative!r}",
        )


def _root_digest(files: dict[str, bytes]) -> str:
    digest = sha256()
    for relative in sorted(files):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(files[relative]).digest())
    return digest.hexdigest()


def _has_symlink_component(root: Path, path: Path) -> bool:
    """Check every lexical component at and below the approved package root."""

    relative = path.relative_to(root)
    current = root
    if current.is_symlink():
        return True
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False
