"""Walking-skeleton CLI commands (ARCH §4, §5, §8, §15; issue #16).

One free-form task flows through: ``task create`` → ``dispatch`` (Coder) →
``collect`` → ``qa`` (Tester on the other harness) → ``collect`` → ``task
complete`` (QA gate) → ``integrate`` → ``deliver`` (``local-only``). Usage is
recorded at every collect.

Every mutating command checks its preconditions before any effect and refuses
with all unmet conditions rather than guessing. A command run from inside a
role agent (``MILBURN_ATTEMPT_ID`` set) is refused (ARCH §3).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping

from milburn.agents.codex_adapter import (
    AgentAdapter,
    AgentEndpoint,
    ClaudeCodeAdapter,
    CodexAdapter,
    LaunchRequest,
)
from milburn.agents.harness import Harness, RunEnd
from milburn.domain import CoderOutcome, CoderResult, QAOutcome, QAReport, Role
from milburn.domain.events import EventType
from milburn.persistence.sqlite_store import SQLiteEventStore
from milburn.runtime.run_host import DetachedRunRuntime

from .project import Project, ProjectError, git
from .state import Attempt, Ledger, ProjectState, Task, WorkItem

RULES_ROOT = Path(__file__).resolve().parents[1] / "agents" / "role_rules"
PROGRESS_FILE = "progress.txt"


class CommandRefused(RuntimeError):
    """A command's preconditions do not hold; nothing was changed."""

    def __init__(self, reasons: list[str] | str) -> None:
        self.reasons = [reasons] if isinstance(reasons, str) else list(reasons)
        super().__init__("; ".join(self.reasons))


@dataclass(frozen=True, slots=True)
class Outcome:
    summary: str
    data: dict[str, Any]


def refuse_inside_role_agent(environ: Mapping[str, str]) -> None:
    if environ.get("MILBURN_ATTEMPT_ID"):
        raise CommandRefused(
            "mutating commands cannot run inside a role agent (MILBURN_ATTEMPT_ID is set)"
        )


class Commands:
    def __init__(self, project: Project, store: SQLiteEventStore) -> None:
        self.project = project
        self.ledger = Ledger(store)

    # ------------------------------------------------------------------ helpers

    def _state(self) -> ProjectState:
        return self.ledger.replay()

    def _seq(self, state: ProjectState, stream: str) -> int:
        return state.sequences.get(stream, -1)

    def _task(self, state: ProjectState, task_id: str) -> Task:
        task = state.tasks.get(task_id)
        if task is None:
            raise CommandRefused(f"unknown task {task_id}")
        return task

    def _head(self, ref: str) -> str:
        return git(self.project.repository, "rev-parse", "--verify", f"{ref}^{{commit}}").stdout.strip()

    def _branch_exists(self, branch: str) -> bool:
        return git(
            self.project.repository, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}",
            check=False,
        ).returncode == 0

    def _runtime(self, endpoint_id: str) -> DetachedRunRuntime:
        return DetachedRunRuntime(self.project.run_dir, endpoint_ids=lambda: endpoint_id)

    def _adapter(self, harness: Harness, runtime: DetachedRunRuntime) -> AgentAdapter:
        executable = self.project.config.executables[harness]
        schema_dir = self.project.state_dir / "schemas"
        if harness is Harness.CODEX:
            return CodexAdapter(runtime, executable=executable, schema_dir=schema_dir)
        return ClaudeCodeAdapter(runtime, executable=executable, schema_dir=schema_dir)

    # ------------------------------------------------------------- work items

    def task_create(
        self, title: str, objective: str, acceptance: list[str], work_item: str | None
    ) -> Outcome:
        reasons = []
        if not title.strip():
            reasons.append("title must not be empty")
        if not objective.strip():
            reasons.append("objective must not be empty")
        if not acceptance or any(not item.strip() for item in acceptance):
            reasons.append("at least one non-empty acceptance criterion is required")
        if reasons:
            raise CommandRefused(reasons)
        state = self._state()
        if work_item is None:
            work_item = self._open_work_item(state, title)
            state = self._state()
        elif work_item not in state.work_items:
            raise CommandRefused(f"unknown work item {work_item}")
        elif state.work_items[work_item].delivered:
            raise CommandRefused(f"work item {work_item} is already delivered")
        task_id = f"t{len(state.tasks) + 1}"
        branch = f"milburn/{work_item}/{task_id}"
        self.ledger.append(
            "project", self._seq(state, "project"), EventType.TASK_CREATED,
            {
                "task": task_id, "work_item": work_item, "task_type": "code",
                "title": title, "objective": objective, "acceptance": acceptance,
                "branch": branch,
            },
            actor="coordinator", correlation_id=task_id,
        )
        return Outcome(f"created {task_id} in {work_item}", {"task": task_id, "work_item": work_item})

    def _open_work_item(self, state: ProjectState, title: str) -> str:
        work_item = f"w{len(state.work_items) + 1}"
        # Not "milburn/<work_item>": Git cannot hold that branch alongside the
        # task branches "milburn/<work_item>/<task>" (a ref cannot be both a
        # file and a directory).
        branch = f"milburn/{work_item}/integration"
        default = self.project.config.default_branch
        base = self._head(default)
        if self._branch_exists(branch):
            raise CommandRefused(f"branch {branch} already exists; refusing to reuse it")
        worktree = self.project.worktree_root / f"{work_item}-integration"
        if worktree.exists():
            raise CommandRefused(f"{worktree} already exists")
        self.project.worktree_root.mkdir(parents=True, exist_ok=True)
        git(self.project.repository, "worktree", "add", "-b", branch, str(worktree), base)
        self.ledger.append(
            "project", self._seq(state, "project"), EventType.WORK_ITEM_OPENED,
            {
                "work_item": work_item, "title": title, "base_sha": base,
                "branch": branch, "integration_worktree": str(worktree),
            },
            actor="controller", correlation_id=work_item,
        )
        return work_item

    # ---------------------------------------------------------------- dispatch

    def dispatch(self, task_id: str, role: str) -> Outcome:
        if role not in ("coder", "tester"):
            raise CommandRefused("role must be coder or tester")
        state = self._state()
        task = self._task(state, task_id)
        work = state.work_items[task.work_item]
        reasons: list[str] = []
        if task.completed:
            reasons.append(f"{task_id} is already completed")
        running = [a.attempt_id for a in task.attempts if a.collected is None]
        if running:
            reasons.append(f"{task_id} has an uncollected attempt {running[-1]}; collect it first")
        coder = task.latest("coder")
        if role == "tester":
            candidate = (coder.collected or {}) if coder else {}
            if not coder or not candidate.get("candidate_ok"):
                reasons.append("the latest Coder attempt has no accepted candidate")
        if reasons:
            raise CommandRefused(reasons)

        attempt_id = f"a{len(task.attempts) + 1}"
        if role == "coder":
            role_config = self.project.config.coder
            worktree = self.project.worktree_root / task_id
            if self._branch_exists(task.branch):
                base = self._head(task.branch)
            else:
                base = self._head(work.branch)
            if not worktree.exists():
                if self._branch_exists(task.branch):
                    git(self.project.repository, "worktree", "add", str(worktree), task.branch)
                else:
                    git(self.project.repository, "worktree", "add", "-b", task.branch, str(worktree), base)
            sandbox = "workspace-write"
            # No --add-dir for Git: Codex keeps Git metadata read-only anyway,
            # and collect commits leftovers (ARCH §6, "Who commits").
            writable: tuple[str, ...] = ()
            candidate_sha = None
        else:
            role_config = self.project.config.tester
            candidate_sha = coder.collected["head_sha"]  # type: ignore[union-attr]
            coder_harness = Harness(coder.harness)  # type: ignore[union-attr]
            if (
                self.project.config.tester_independence == "other-than-coder"
                and role_config.harness is coder_harness
            ):
                raise CommandRefused(
                    f"the Tester harness {role_config.harness.value} equals the Coder's; "
                    "independent QA needs another harness"
                )
            worktree = self.project.worktree_root / f"{task_id}-qa-{attempt_id}"
            if worktree.exists():
                raise CommandRefused(f"{worktree} already exists")
            git(self.project.repository, "worktree", "add", "--detach", str(worktree), candidate_sha)
            base = candidate_sha
            sandbox = "read-only"
            writable = ()

        endpoint_id = f"{task_id}-{attempt_id}"
        runtime = self._runtime(endpoint_id)
        adapter = self._adapter(role_config.harness, runtime)
        request = LaunchRequest(
            role=Role.CODER if role == "coder" else Role.TESTER,
            task_id=task_id,
            attempt_id=attempt_id,
            worktree=str(worktree),
            objective=task.objective,
            role_rules=_role_rules(role),
            task_context=_task_context(task, role, base, candidate_sha),
            repository_instructions=(
                "Read AGENTS.md or CLAUDE.md in the repository if present. Preserve "
                "unrelated work. Do not push, merge, or open pull requests."
            ),
            expected_result_type="coder_result" if role == "coder" else "qa_report",
            sandbox=sandbox,
            writable_dirs=writable,
            model=role_config.model,
        )
        endpoint = adapter.launch(request)
        self.ledger.append(
            f"task-{task_id}", self._seq(state, f"task-{task_id}"), EventType.ATTEMPT_DISPATCHED,
            {
                "task": task_id, "attempt": attempt_id, "role": role,
                "harness": role_config.harness.value, "endpoint": endpoint.runtime_endpoint,
                "worktree": str(worktree), "base_sha": base, "sandbox": sandbox,
                "expected_result_type": endpoint.expected_result_type,
                "brief_digest": endpoint.brief_digest, "rules_digest": endpoint.rules_digest,
                "candidate_sha": candidate_sha,
            },
            actor="controller", correlation_id=task_id,
        )
        return Outcome(
            f"dispatched {role} {task_id}/{attempt_id} on {role_config.harness.value}",
            {"task": task_id, "attempt": attempt_id, "harness": role_config.harness.value,
             "worktree": str(worktree)},
        )

    # ----------------------------------------------------------------- collect

    def collect(self, task_id: str, wait_seconds: float = 0) -> Outcome:
        state = self._state()
        task = self._task(state, task_id)
        pending = [a for a in task.attempts if a.collected is None]
        if not pending:
            raise CommandRefused(f"{task_id} has no attempt to collect")
        attempt = pending[-1]
        runtime = self._runtime(attempt.endpoint)
        if wait_seconds > 0:
            runtime.wait(attempt.endpoint, wait_seconds)
        dispatched = _dispatch_payload(self.ledger, task_id, attempt.attempt_id)
        endpoint = AgentEndpoint(
            runtime_endpoint=attempt.endpoint,
            role=Role.CODER if attempt.role == "coder" else Role.TESTER,
            task_id=task_id,
            attempt_id=attempt.attempt_id,
            expected_result_type=dispatched["expected_result_type"],
            expected_result_schema_version=1,
            brief_digest=dispatched["brief_digest"],
            rules_digest=dispatched["rules_digest"],
            skill_bindings=(),
            harness=Harness(attempt.harness),
        )
        result = self._adapter(Harness(attempt.harness), runtime).collect(endpoint)
        if result.process_exit is None and result.protocol_error is None:
            return Outcome(f"{task_id}/{attempt.attempt_id} is still running", {"running": True})

        record: dict[str, Any] = {
            "task": task_id,
            "attempt": attempt.attempt_id,
            "role": attempt.role,
            "run_end": result.run_end.value,
            "exit_code": result.process_exit.exit_code if result.process_exit else None,
            "protocol_error": result.protocol_error,
            "session_id": result.session_id,
            "task_success": result.task_result.task_success if result.task_result else None,
            "result": result.task_result.payload.to_dict() if result.task_result else None,
        }
        if attempt.role == "coder":
            record.update(self._check_candidate(task, attempt, result.task_result))
        else:
            record.update(_qa_summary(result.task_result, dispatched["candidate_sha"]))
        sequence = self._seq(state, f"task-{task_id}")
        self.ledger.append(
            f"task-{task_id}", sequence, EventType.ATTEMPT_COLLECTED, record,
            actor="controller", correlation_id=task_id,
        )
        if result.usage is not None:
            usage = {
                "task": task_id, "attempt": attempt.attempt_id, "role": attempt.role,
                "harness": attempt.harness,
                **{name: getattr(result.usage, name) for name in (
                    "input_tokens", "cached_input_tokens", "cache_write_tokens",
                    "output_tokens", "reasoning_tokens",
                )},
            }
            self.ledger.append(
                f"task-{task_id}", sequence + 1, EventType.AGENT_USAGE_OBSERVED, usage,
                actor="controller", correlation_id=task_id,
            )
        verdict = record.get("candidate_ok", record.get("qa_outcome"))
        detail = (
            "error: " + result.protocol_error
            if result.protocol_error
            else f"result {verdict}"
        )
        if record.get("candidate_reasons"):
            detail += " (" + "; ".join(record["candidate_reasons"]) + ")"
        return Outcome(
            f"collected {task_id}/{attempt.attempt_id}: run {result.run_end.value}, {detail}",
            record,
        )

    def _commit_leftovers(self, task: Task, attempt: Attempt) -> str | None:
        """Commit what the Coder left in its worktree, under its own identity.

        Codex keeps the Git directory read-only under workspace-write, so a
        Codex Coder cannot commit (docs/harness-facts.md); the CLI makes the
        commit for it (ARCH §6). Returns the new commit SHA, if any.
        """

        worktree = Path(attempt.worktree)
        if not git(worktree, "status", "--porcelain", "--untracked-files=all").stdout.strip():
            return None
        name = f"Milburn coder [{task.task_id}/{attempt.attempt_id}]"
        email = f"coder.{task.task_id}.{attempt.attempt_id}@milburn.invalid"
        identity = (
            "-c", f"user.name={name}", "-c", f"user.email={email}",
        )
        git(worktree, "add", "-A")
        git(
            worktree, *identity, "commit", "-q", "-m",
            f"{task.task_id}: {task.title}\n\nCommitted by Milburn for attempt "
            f"{attempt.attempt_id}; the Coder's harness could not write Git.",
        )
        return git(worktree, "rev-parse", "HEAD").stdout.strip()

    def _check_candidate(self, task: Task, attempt: Attempt, parsed: Any) -> dict[str, Any]:
        """Mechanical candidate checks (the core of ``candidate-protocol``)."""

        reasons: list[str] = []
        payload = parsed.payload if parsed else None
        if not isinstance(payload, CoderResult):
            return {"candidate_ok": False, "candidate_reasons": ["no valid Coder result"],
                    "head_sha": None, "outcome": None}
        if payload.outcome is not CoderOutcome.CANDIDATE:
            return {"candidate_ok": False, "outcome": payload.outcome.value,
                    "candidate_reasons": [f"Coder reported {payload.outcome.value}"],
                    "head_sha": payload.head_sha}
        worktree = Path(attempt.worktree)
        reported_against = git(worktree, "rev-parse", "HEAD").stdout.strip()
        if payload.head_sha != reported_against:
            reasons.append(
                f"reported head {payload.head_sha} is not the worktree head {reported_against}"
            )
        cli_commit = self._commit_leftovers(task, attempt)
        head = git(worktree, "rev-parse", "HEAD").stdout.strip()
        branch_head = self._head(task.branch)
        if head != branch_head:
            reasons.append(f"the worktree head {head} is not the task branch head {branch_head}")
        if git(worktree, "status", "--porcelain", "--untracked-files=all").stdout.strip():
            reasons.append("the task worktree still has uncommitted changes")
        if git(worktree, "merge-base", "--is-ancestor", attempt.base_sha, head, check=False).returncode:
            reasons.append("the candidate does not descend from the attempt base")
        new_commits = set(
            git(worktree, "rev-list", f"{attempt.base_sha}..{head}").stdout.split()
        )
        if not new_commits:
            reasons.append("the candidate adds no commits")
        listed = set(payload.commits)
        unknown = sorted(
            commit for commit in listed
            if not any(full.startswith(commit) for full in new_commits)
        )
        if unknown:
            reasons.append(f"reported commits are not on the branch: {unknown}")
        return {"candidate_ok": not reasons, "candidate_reasons": reasons,
                "head_sha": head, "outcome": payload.outcome.value,
                "cli_commit": cli_commit}

    # ------------------------------------------------------------------ QA gate

    def complete(self, task_id: str) -> Outcome:
        state = self._state()
        task = self._task(state, task_id)
        reasons = qa_gate(task, self.project.config.tester_independence, self._head_or_none(task.branch))
        if reasons:
            self.ledger.append(
                f"task-{task_id}", self._seq(state, f"task-{task_id}"), EventType.QA_GATE_REFUSED,
                {"task": task_id, "reasons": reasons}, actor="controller", correlation_id=task_id,
            )
            raise CommandRefused(reasons)
        coder = task.latest("coder")
        tester = task.latest("tester")
        self.ledger.append(
            f"task-{task_id}", self._seq(state, f"task-{task_id}"), EventType.TASK_COMPLETED,
            {
                "task": task_id, "candidate_sha": coder.collected["head_sha"],  # type: ignore[union-attr]
                "coder_attempt": coder.attempt_id, "coder_harness": coder.harness,  # type: ignore[union-attr]
                "qa_attempt": tester.attempt_id, "qa_harness": tester.harness,  # type: ignore[union-attr]
            },
            actor="controller", correlation_id=task_id,
        )
        return Outcome(f"{task_id} completed: independent QA passed", {"task": task_id})

    def _head_or_none(self, branch: str) -> str | None:
        return self._head(branch) if self._branch_exists(branch) else None

    # --------------------------------------------------------------- delivery

    def integrate(self, task_id: str) -> Outcome:
        state = self._state()
        task = self._task(state, task_id)
        work = state.work_items[task.work_item]
        reasons = []
        if not task.completed:
            reasons.append(f"{task_id} has not passed the QA gate")
        if task.integrated:
            reasons.append(f"{task_id} is already integrated")
        if task.completed and self._head(task.branch) != task.completed["candidate_sha"]:
            reasons.append(f"{task.branch} moved after QA passed; QA must run again")
        if reasons:
            raise CommandRefused(reasons)
        worktree = Path(work.integration_worktree)
        identity = (
            "-c", "user.name=Milburn controller", "-c", "user.email=controller@milburn.invalid",
        )
        merged = git(
            worktree, *identity, "merge", "--no-ff", "--no-edit",
            "-m", f"Merge {task_id}: {task.title}", task.branch, check=False,
        )
        if merged.returncode != 0:
            git(worktree, "merge", "--abort", check=False)
            raise CommandRefused(
                f"{task.branch} does not merge cleanly into {work.branch}; "
                "dispatch a Coder rework attempt that merges the integration head first"
            )
        merge_sha = git(worktree, "rev-parse", "HEAD").stdout.strip()
        self.ledger.append(
            f"task-{task_id}", self._seq(state, f"task-{task_id}"), EventType.TASK_INTEGRATED,
            {"task": task_id, "merge_sha": merge_sha, "work_item": work.work_item},
            actor="controller", correlation_id=task_id,
        )
        return Outcome(f"integrated {task_id} into {work.branch} at {merge_sha[:12]}",
                       {"merge_sha": merge_sha})

    def deliver(self, work_item: str) -> Outcome:
        state = self._state()
        work = state.work_items.get(work_item)
        if work is None:
            raise CommandRefused(f"unknown work item {work_item}")
        reasons = []
        if work.delivered:
            reasons.append(f"{work_item} is already delivered")
        if not work.tasks:
            reasons.append(f"{work_item} has no tasks")
        for task_id in work.tasks:
            if not state.tasks[task_id].integrated:
                reasons.append(f"{task_id} is not integrated")
        mode = self.project.config.delivery
        if mode != "local-only":
            reasons.append(f"delivery mode {mode} is not available yet (#68); use local-only")
        if reasons:
            raise CommandRefused(reasons)
        head = self._head(work.branch)
        self.ledger.append(
            f"work-{work_item}", self._seq(state, f"work-{work_item}"), EventType.WORK_ITEM_DELIVERED,
            {"work_item": work_item, "mode": mode, "head_sha": head, "branch": work.branch},
            actor="controller", correlation_id=work_item,
        )
        return Outcome(
            f"delivered {work_item} ({mode}): branch {work.branch} at {head[:12]}, not pushed",
            {"head_sha": head},
        )

    # ------------------------------------------------------------------ reports

    def status(self) -> Outcome:
        state = self._state()
        lines = []
        for work in state.work_items.values():
            delivered = "delivered" if work.delivered else "open"
            lines.append(f"{work.work_item} [{delivered}] {work.title} ({work.branch})")
            for task_id in work.tasks:
                task = state.tasks[task_id]
                lines.append(f"  {task_id} [{_task_phase(task)}] {task.title}")
        if not lines:
            lines.append("no work items")
        return Outcome("\n".join(lines), {"lines": lines})

    def usage(self) -> Outcome:
        state = self._state()
        totals: dict[tuple[str, str, str], dict[str, int]] = {}
        for row in state.usage:
            key = (row["task"], row["role"], row["harness"])
            bucket = totals.setdefault(key, {})
            for name in ("input_tokens", "cached_input_tokens", "output_tokens"):
                if row.get(name) is not None:
                    bucket[name] = bucket.get(name, 0) + row[name]
            bucket["attempts"] = bucket.get("attempts", 0) + 1
        lines = [
            f"{task} {role} {harness}: " + ", ".join(f"{k}={v}" for k, v in sorted(values.items()))
            for (task, role, harness), values in sorted(totals.items())
        ] or ["no usage recorded"]
        return Outcome("\n".join(lines), {"rows": state.usage})


def qa_gate(task: Task, independence: str, branch_head: str | None) -> list[str]:
    """ARCH §8 conditions 1-4 and 6 for the skeleton. Pure; returns unmet conditions."""

    reasons: list[str] = []
    if task.completed:
        return [f"{task.task_id} is already completed"]
    coder = task.latest("coder")
    tester = task.latest("tester")
    coder_result = coder.collected if coder else None
    if not coder_result or not coder_result.get("candidate_ok"):
        reasons.append("no accepted Coder candidate")
    elif coder_result.get("head_sha") != branch_head:
        reasons.append("the task branch moved after the candidate was accepted")
    if not tester or tester.collected is None:
        reasons.append("no collected Tester report")
        return reasons
    report = tester.collected
    if tester.role != "tester" or (coder and tester.attempt_id == coder.attempt_id):
        reasons.append("the QA report is not from a separate Tester attempt")
    if report.get("run_end") != RunEnd.COMPLETED.value:
        reasons.append(f"the Tester run ended {report.get('run_end')}")
    if report.get("qa_outcome") != QAOutcome.PASSED.value:
        reasons.append(f"QA outcome is {report.get('qa_outcome')}, not passed")
    if coder_result and report.get("qa_candidate_sha") != coder_result.get("head_sha"):
        reasons.append("the QA report names a different candidate SHA")
    if coder and independence == "other-than-coder" and tester.harness == coder.harness:
        reasons.append("the Tester ran on the Coder's harness")
    if report.get("qa_defects"):
        reasons.append("the passed QA report lists open defects")
    return reasons


def _qa_summary(parsed: Any, candidate_sha: str | None) -> dict[str, Any]:
    payload = parsed.payload if parsed else None
    if not isinstance(payload, QAReport):
        return {"qa_outcome": None, "qa_candidate_sha": None, "qa_defects": []}
    outcome = payload.outcome.value
    if payload.candidate_sha != candidate_sha:
        outcome = "mismatched-candidate"
    return {
        "qa_outcome": outcome,
        "qa_candidate_sha": payload.candidate_sha,
        "qa_defects": list(payload.defects),
    }


def _task_phase(task: Task) -> str:
    if task.integrated:
        return "integrated"
    if task.completed:
        return "completed"
    if not task.attempts:
        return "ready"
    latest = task.attempts[-1]
    if latest.collected is None:
        return f"{latest.role} {latest.attempt_id} running"
    return f"{latest.role} {latest.attempt_id} collected"


def _role_rules(role: str) -> str:
    if role == "coder":
        files = sorted((RULES_ROOT / "coder").glob("*.md"))
    else:
        files = [RULES_ROOT / "tester.md"]
    return "\n\n".join(path.read_text(encoding="utf-8").strip() for path in files)


def _task_context(task: Task, role: str, base: str, candidate: str | None) -> str:
    criteria = "\n".join(f"- {item}" for item in task.acceptance)
    lines = [
        f"Task {task.task_id}: {task.title}",
        f"Branch: {task.branch}",
        f"Base revision: {base}",
        "Acceptance criteria:",
        criteria,
    ]
    if role == "coder":
        lines += [
            f"Keep your progress in {PROGRESS_FILE} at the worktree root and commit it.",
            f"Use issue_number {int(task.task_id[1:])} and progress_path {PROGRESS_FILE} in your result.",
            "Commit your work on the current branch if your sandbox allows it. If a commit "
            "fails, leave the changes in the worktree: Milburn commits them for you when it "
            "collects your result. Report outcome candidate with head_sha set to the current "
            "HEAD and commits listing the commits you made (empty if none).",
        ]
    else:
        lines += [
            f"Candidate SHA under test: {candidate}",
            f"Use issue_number {int(task.task_id[1:])} and candidate_sha {candidate} in your report.",
            "Test the checkout as it is; do not commit. Report passed only if every criterion holds.",
        ]
    return "\n".join(lines)


def _dispatch_payload(ledger: Ledger, task_id: str, attempt_id: str) -> dict[str, Any]:
    from .state import payload_of

    for event in ledger._store.read_stream(f"task-{task_id}"):
        if event.event_type is EventType.ATTEMPT_DISPATCHED:
            data = payload_of(event)
            if data["attempt"] == attempt_id:
                return data
    raise ProjectError(f"no dispatch record for {task_id}/{attempt_id}")
