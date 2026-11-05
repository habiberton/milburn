"""Project layout and configuration for the ``milburn`` CLI (ARCH §4, §6, A3).

The configuration lives in the target repository at ``.milburn/config.toml``.
Milburn's own state lives outside every writable root, under
``$MILBURN_HOME/projects/<project-id>/`` (default ``~/.milburn``):

- ``events.sqlite``: the event store.
- ``runs/``: detached run files (``runtime/run_host.py``).
- ``worktrees/``: task and integration worktrees.

The project ID is derived from the repository's shared Git directory, so every
worktree of one repository maps to the same project.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tomllib
from typing import Iterator, Mapping

from milburn.agents.harness import Harness

CONFIG_RELATIVE = Path(".milburn") / "config.toml"
DELIVERY_MODES = ("local-only", "pr", "auto-merge")
ROLES = ("coder", "tester")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

DEFAULT_CONFIG = """\
# Milburn project configuration (ARCH §6). Managed by `milburn init`.

[project]
# local-only | pr | auto-merge (only local-only is available yet)
delivery = "local-only"
default_branch = "{default_branch}"

[roles.coder]
harness = "codex"

[roles.tester]
harness = "claude-code"
# "other-than-coder" (default) or "any"
independence = "other-than-coder"
"""


class ProjectError(RuntimeError):
    """The repository or its Milburn configuration cannot be used."""


@dataclass(frozen=True, slots=True)
class RoleConfig:
    harness: Harness
    model: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    delivery: str
    default_branch: str
    coder: RoleConfig
    tester: RoleConfig
    tester_independence: str
    executables: Mapping[Harness, str]


@dataclass(frozen=True, slots=True)
class Project:
    repository: Path
    git_common_dir: Path
    state_dir: Path
    config: ProjectConfig

    @property
    def store_path(self) -> Path:
        return self.state_dir / "events.sqlite"

    @property
    def run_dir(self) -> Path:
        return self.state_dir / "runs"

    @property
    def worktree_root(self) -> Path:
        return self.state_dir / "worktrees"

    def expected_gitdir(self, worktree: Path) -> Path:
        """The admin directory Git creates for a linked worktree we add."""

        return self.git_common_dir / "worktrees" / worktree.name

    @contextmanager
    def mutation_lock(self) -> Iterator[None]:
        """Serialize mutating CLI commands for one project (ARCH §4)."""

        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_dir / "cli.lock", "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def git(repository: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run Git for the CLI with hooks and fsmonitor disabled (ARCH §4)."""

    empty_hooks = Path(os.devnull)
    # Inherited GIT_* variables (identity, index file, directories) would
    # override the explicit arguments below; the CLI never inherits them.
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    completed = subprocess.run(
        (
            "git", "-c", f"core.hooksPath={empty_hooks}", "-c", "core.fsmonitor=false",
            *arguments,
        ),
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    if check and completed.returncode != 0:
        raise ProjectError(
            f"git {' '.join(arguments)} failed: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed


def agent_git(
    project: "Project", worktree: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run Git in a role agent's worktree without trusting its ``.git`` file.

    The ``.git`` file sits inside the agent's writable root; an agent could
    repoint it at a gitdir it controls. The CLI checks the pointer and passes
    the expected gitdir and work tree explicitly.
    """

    gitdir = project.expected_gitdir(worktree)
    pointer = worktree / ".git"
    try:
        content = pointer.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ProjectError(f"{pointer} is unreadable: {error}") from error
    resolved_gitdir = gitdir.resolve()
    if not content.startswith("gitdir: ") or Path(content[8:]).resolve() != resolved_gitdir:
        raise ProjectError(f"{pointer} does not point at {gitdir}; refusing to use it")
    return git(
        worktree,
        f"--git-dir={resolved_gitdir}",
        f"--work-tree={worktree}",
        *arguments,
        check=check,
    )


def milburn_home(environ: Mapping[str, str] | None = None) -> Path:
    environ = os.environ if environ is None else environ
    value = environ.get("MILBURN_HOME")
    home = Path(value) if value else Path.home() / ".milburn"
    if not home.is_absolute():
        raise ProjectError("MILBURN_HOME must be an absolute path")
    return home


def repository_root(cwd: Path) -> tuple[Path, Path]:
    """Return the main repository root and its shared Git directory."""

    inside = subprocess.run(
        ("git", "rev-parse", "--path-format=absolute", "--git-common-dir"),
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if inside.returncode != 0:
        raise ProjectError("not inside a Git repository")
    common = Path(inside.stdout.strip()).resolve()
    if common.name != ".git":
        raise ProjectError("bare repositories are not supported")
    return common.parent, common


def project_id(common_dir: Path) -> str:
    return hashlib.sha256(str(common_dir).encode("utf-8")).hexdigest()[:16]


def parse_config(text: str, executables_env: Mapping[str, str]) -> ProjectConfig:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ProjectError(f"invalid .milburn/config.toml: {error}") from error
    _only(data, {"project", "roles"}, "config")
    project = data.get("project")
    roles = data.get("roles")
    if not isinstance(project, dict) or not isinstance(roles, dict):
        raise ProjectError("config needs [project] and [roles] tables")
    _only(project, {"delivery", "default_branch"}, "[project]")
    delivery = project.get("delivery", "pr")
    if delivery not in DELIVERY_MODES:
        raise ProjectError(f"delivery must be one of {DELIVERY_MODES}")
    branch = project.get("default_branch")
    if not isinstance(branch, str) or not _NAME.fullmatch(branch.replace("/", "-")):
        raise ProjectError("[project] default_branch must be a branch name")
    _only(roles, set(ROLES), "[roles]")
    parsed: dict[str, RoleConfig] = {}
    independence = "other-than-coder"
    for role in ROLES:
        table = roles.get(role)
        if not isinstance(table, dict):
            raise ProjectError(f"[roles.{role}] is required")
        allowed = {"harness", "model"} | ({"independence"} if role == "tester" else set())
        _only(table, allowed, f"[roles.{role}]")
        try:
            harness = Harness(table.get("harness"))
        except ValueError as error:
            raise ProjectError(
                f"[roles.{role}] harness must be one of {[h.value for h in Harness]}"
            ) from error
        model = table.get("model")
        if model is not None and (not isinstance(model, str) or not _NAME.fullmatch(model)):
            raise ProjectError(f"[roles.{role}] model must be a model name")
        parsed[role] = RoleConfig(harness, model)
        if role == "tester":
            independence = table.get("independence", "other-than-coder")
            if independence not in ("other-than-coder", "any"):
                raise ProjectError("[roles.tester] independence must be other-than-coder or any")
    if independence == "other-than-coder" and parsed["coder"].harness is parsed["tester"].harness:
        raise ProjectError(
            "the Tester must run on a different harness from the Coder "
            "(set [roles.tester] independence = \"any\" to allow the same harness)"
        )
    executables = {
        Harness.CODEX: executables_env.get("MILBURN_CODEX_EXECUTABLE", "codex"),
        Harness.CLAUDE_CODE: executables_env.get("MILBURN_CLAUDE_EXECUTABLE", "claude"),
    }
    return ProjectConfig(
        delivery=delivery,
        default_branch=branch,
        coder=parsed["coder"],
        tester=parsed["tester"],
        tester_independence=independence,
        executables=executables,
    )


def _only(table: Mapping[str, object], allowed: set[str], where: str) -> None:
    unknown = set(table) - allowed
    if unknown:
        raise ProjectError(f"{where} has unknown keys {sorted(unknown)}")


def load_project(cwd: Path, environ: Mapping[str, str] | None = None) -> Project:
    environ = os.environ if environ is None else environ
    root, common = repository_root(cwd)
    config_path = root / CONFIG_RELATIVE
    if not config_path.is_file():
        raise ProjectError("no .milburn/config.toml; run `milburn init` first")
    config = parse_config(config_path.read_text(encoding="utf-8"), environ)
    state = milburn_home(environ) / "projects" / project_id(common)
    return Project(root, common, state, config)


def init_project(cwd: Path, environ: Mapping[str, str] | None = None) -> tuple[Project, bool]:
    """Create the config (if missing) and the private state directories."""

    environ = os.environ if environ is None else environ
    root, common = repository_root(cwd)
    config_path = root / CONFIG_RELATIVE
    created = False
    if not config_path.exists():
        head = git(root, "symbolic-ref", "--short", "HEAD", check=False)
        branch = head.stdout.strip() if head.returncode == 0 else "main"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(DEFAULT_CONFIG.format(default_branch=branch), encoding="utf-8")
        created = True
    project = load_project(cwd, environ)
    for directory in (project.state_dir, project.run_dir, project.worktree_root):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
    return project, created
