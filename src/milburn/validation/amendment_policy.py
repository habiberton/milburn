"""Controller policy for amendment dispatch and coordinator preflights."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from milburn.persistence.amendment_projections import AmendmentProjection


class PlanChangeKind(StrEnum):
    SCOPE = "scope"
    POLICY = "policy"
    SPECIFICATION = "specification"
    TASK = "task"
    DEPENDENCY = "dependency"
    WAVE = "wave"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    DISPATCH_RULE = "dispatch_rule"


class DispatchFrozenError(RuntimeError):
    """Raised before any launch intent or effect while planning is unsafe."""


@dataclass(frozen=True, slots=True)
class AmendmentPreflight:
    pending_amendments: tuple[str, ...]
    dirty_planning_paths: tuple[str, ...]

    @property
    def dispatch_allowed(self) -> bool:
        return not self.pending_amendments and not self.dirty_planning_paths

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers = [
            f"plan amendment {amendment_id} still freezes dispatch"
            for amendment_id in self.pending_amendments
        ]
        if self.dirty_planning_paths:
            blockers.append(
                "coordinator planning files are uncommitted: "
                + ", ".join(self.dirty_planning_paths)
            )
        return tuple(blockers)


def requires_plan_amendment(change_kind: PlanChangeKind) -> bool:
    """Make the user-authorized plan-change boundary explicit and exhaustive."""

    if not isinstance(change_kind, PlanChangeKind):
        raise ValueError("change_kind must be a known PlanChangeKind")
    return True


def plan_amendment_preflight(
    amendments: Iterable[AmendmentProjection],
    *,
    dirty_planning_paths: Iterable[str] = (),
) -> AmendmentPreflight:
    pending = tuple(
        sorted(state.amendment_id for state in amendments if state.dispatch_frozen)
    )
    dirty = tuple(sorted(set(dirty_planning_paths)))
    return AmendmentPreflight(pending, dirty)


def ensure_agent_launch_allowed(
    amendments: Iterable[AmendmentProjection],
    *,
    dirty_planning_paths: Iterable[str] = (),
) -> None:
    """Reject before recording AgentLaunchRequested or crossing an effect boundary."""

    preflight = plan_amendment_preflight(
        amendments, dirty_planning_paths=dirty_planning_paths
    )
    if not preflight.dispatch_allowed:
        raise DispatchFrozenError("; ".join(preflight.blockers))
