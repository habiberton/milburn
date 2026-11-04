"""Mandatory authority-rule loading kept separate from procedural skills."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from milburn.domain import Role


class RoleRuleError(ValueError):
    """Raised when mandatory role authority text is incomplete."""


@dataclass(frozen=True, slots=True)
class RoleRules:
    role: Role
    content: str
    digest: str
    authority_limits: tuple[str, ...]


class RoleRuleCatalog:
    def __init__(self, rules_root: Path, policies_path: Path) -> None:
        self._rules_root = rules_root.absolute()
        if self._rules_root.is_symlink() or not self._rules_root.is_dir():
            raise RoleRuleError("role rules root must be a real directory")
        self._policies = _load_policies(policies_path)

    def load(self, role: Role) -> RoleRules:
        if not isinstance(role, Role):
            raise RoleRuleError("role must be a known Milburn role")
        policy = self._policies[role]
        sections: list[str] = []
        for relative in policy["rule_files"]:
            path = _contained_rule_path(self._rules_root, relative, role)
            sections.append(path.read_text(encoding="utf-8").strip())
        content = "\n\n".join(sections) + "\n"
        if not content.strip():
            raise RoleRuleError(f"role rule file is empty for {role.value}")
        limits = tuple(policy["authority_limits"])
        lowered = content.casefold()
        missing = [limit for limit in limits if limit.casefold() not in lowered]
        if missing:
            raise RoleRuleError(
                f"role rules for {role.value} omit mandatory limits: "
                + ", ".join(missing)
            )
        if any(token in lowered for token in ("todo", "tbd", "fixme", "placeholder")):
            raise RoleRuleError(f"role rules for {role.value} contain a placeholder")
        return RoleRules(
            role=role,
            content=content,
            digest=sha256(content.encode("utf-8")).hexdigest(),
            authority_limits=limits,
        )


def _load_policies(path: Path) -> dict[Role, dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RoleRuleError(f"cannot read role policies: {error}") from error
    if not isinstance(payload, dict) or set(payload) != {"roles"}:
        raise RoleRuleError("role policies must contain only roles")
    raw_roles = payload["roles"]
    if not isinstance(raw_roles, dict) or set(raw_roles) != {role.value for role in Role}:
        raise RoleRuleError("role policies must define every known role")
    policies: dict[Role, dict[str, object]] = {}
    for role in Role:
        entry = raw_roles[role.value]
        if not isinstance(entry, dict) or set(entry) != {"rule_files", "authority_limits"}:
            raise RoleRuleError(f"invalid policy for {role.value}")
        rule_files = entry["rule_files"]
        limits = entry["authority_limits"]
        if (
            not isinstance(rule_files, list)
            or not rule_files
            or any(
                not isinstance(value, str)
                or Path(value).is_absolute()
                or ".." in Path(value).parts
                for value in rule_files
            )
            or not isinstance(limits, list)
            or not limits
            or any(not isinstance(limit, str) or not limit.strip() for limit in limits)
        ):
            raise RoleRuleError(f"invalid policy values for {role.value}")
        if len(rule_files) != len(set(rule_files)):
            raise RoleRuleError(f"duplicate role rule files for {role.value}")
        policies[role] = entry
    return policies


def _contained_rule_path(root: Path, relative: str, role: Role) -> Path:
    """Reject rule files whose lexical path crosses any symlink boundary."""

    path = root / relative
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise RoleRuleError(
                f"role rule path has a symlinked component for {role.value}: {relative}"
            )
    try:
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        resolved_path.relative_to(resolved_root)
    except (OSError, ValueError) as error:
        raise RoleRuleError(
            f"role rule path escapes the approved root for {role.value}: {relative}"
        ) from error
    if not resolved_path.is_file():
        raise RoleRuleError(f"role rule file is missing for {role.value}: {relative}")
    return resolved_path
