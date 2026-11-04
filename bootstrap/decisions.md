# Bootstrap decisions

## 2026-11-03 — Product and architecture are approved inputs

The bootstrap coordinator implements `PRD.md` and `ARCH.md`. It does not launch
agents to review or replace the architecture. Direct contradictions or
impossible requirements are escalated to the user.

## 2026-11-03 — Root-owned coordination

The root Codex agent owns the task registry, primary checkout, worktree
creation, integration, and completion. Worker agents receive one bounded task
in one worktree and cannot spawn additional agents.

## 2026-11-03 — Parallelism begins after shared foundations

Wave 1 is sequential. Later waves may run independent tasks in parallel after
their dependencies and shared interfaces are integrated. The bootstrap limit is
three implementation workers, with two preferred initially.

## 2026-11-03 — Per-task progress records

Workers do not share one progress file. The coordinator has one integration
record, and every task has its own progress record to avoid merge conflicts and
make recovery task-specific.

## 2026-11-03 — Bootstrap state is separate from Milburn state

Temporary build coordination lives under `bootstrap/`. The `.milburn/`
namespace is reserved for the product's future runtime state.

