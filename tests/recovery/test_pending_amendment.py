"""Restart recovery keeps pending amendments and their dispatch fence."""

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from milburn.domain.amendments import (
    AmendmentCommandType,
    AmendmentStatus,
    PlanAmendmentCommand,
    PlanAmendmentEvent,
)
from milburn.orchestration.plan_amendments import (
    AmendmentConcurrencyError,
    PlanAmendmentCoordinator,
)
from milburn.validation.amendment_policy import DispatchFrozenError


class DurableFileStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read_stream(self, amendment_id: str) -> tuple[PlanAmendmentEvent, ...]:
        if not self.path.exists():
            return ()
        payloads = json.loads(self.path.read_text(encoding="utf-8"))
        return tuple(
            event
            for event in (PlanAmendmentEvent.from_dict(payload) for payload in payloads)
            if event.amendment_id == amendment_id
        )

    def append(self, amendment_id, expected_version, events):
        current = self.read_stream(amendment_id)
        actual = current[-1].sequence if current else -1
        if actual != expected_version:
            raise AmendmentConcurrencyError("stale")
        all_events = (*current, *events)
        self.path.write_text(
            json.dumps([event.to_dict() for event in all_events], sort_keys=True),
            encoding="utf-8",
        )
        return events


def test_restart_preserves_pending_amendment_without_applying_or_dropping_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "amendments.json"
    request = PlanAmendmentCommand(
        command_id="request-1",
        amendment_id="amend-1",
        command_type=AmendmentCommandType.REQUEST,
        expected_version=-1,
        authority="direct user instruction",
        requested_change="Change the active task graph.",
        affected_tasks=("MB-007",),
    )
    first = PlanAmendmentCoordinator(
        DurableFileStore(path),
        clock=lambda: datetime(2026, 11, 3, tzinfo=UTC),
        event_ids=lambda: "event-1",
    )
    recorded = first.handle(request)

    restarted = PlanAmendmentCoordinator(
        DurableFileStore(path),
        clock=lambda: datetime(2026, 11, 4, tzinfo=UTC),
        event_ids=lambda: pytest.fail("idempotent retry must not create an event"),
    )
    recovered = restarted.state("amend-1")
    assert recovered is not None
    assert recovered.status is AmendmentStatus.PENDING
    assert recovered.dispatch_frozen
    assert recovered.last_event_id == recorded.event_id

    assert restarted.handle(request) == recorded
    assert len(DurableFileStore(path).read_stream("amend-1")) == 1
    with pytest.raises(DispatchFrozenError):
        restarted.request_agent_launch(
            (recovered,), request_effect=lambda: pytest.fail("must stay fenced")
        )
