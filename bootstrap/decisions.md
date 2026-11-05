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

## 2026-11-03 — Logical agent identity is enforced in Git

The bootstrap process uses one approved GitHub-linked email and distinct
worktree-local names for Coordinator and worker attempts. Commits include
Milburn role, worker, task, and attempt trailers. The root verifies candidate
metadata before integration. Workers do not receive separate GitHub push
credentials.

## 2026-11-03 — GitHub is the task assignment and status registry

The 16 tasks in `bootstrap/tasks.json` are mirrored to `habiberton/milburn`
issues #1 through #16. GitHub issue assignees are authoritative for assignment;
issue state and the approved `milburn:*` labels are authoritative for lifecycle
status. `bootstrap/tasks.json` retains the dependency graph and recovery
metadata, including the last observed GitHub mapping. No implementation agents
are launched as part of registry initialization.

## 2026-11-04 — Process-tooling tasks do not gate later waves

The AMEND-003 tooling tasks (MB-023 to MB-029, parallel group
`wave-2-process-tooling`) run as a parallel track. They do not hold Wave 3 or
later waves, and an unfinished tooling task, including MB-029 while the
launcher permissions are unset, is not a blocker for starting product tasks
whose own dependencies are done. Their dependencies on each other still apply.
Product tasks still follow the work-wave and parallel-delegation rules among
themselves.

## 2026-11-04 — MB-009 continues under the manual procedure

MB-009 continues through review on its current candidate even though its fix
rounds already exceed AMEND-003's three-round convergence backstop. AMEND-003
classes it as unaffected. Its reviewers still use `gpt-6-sol` with
`fork_turns: none`. If the next full review round finds a blocking finding, the
root records it and asks the user again before another fix round.

## 2026-11-04 — Reviewer model ID confirmed

The user confirmed that `gpt-6-sol` is the reviewer model ID. A reviewer spawn
that cannot use it still fails closed.

## 2026-11-04 — Single-agent build replaces the coordinator model

The remaining core product tasks (MB-010 to MB-016, MB-019, MB-021) are built by
one agent following `bootstrap/SINGLE_AGENT.md`. The coordinator, worker
worktrees and identities, commit trailers, plan-amendment freeze, root rotation,
and the AMEND-003 tooling are suspended. The agent reviews its own work with a
mechanical checklist and a convergence limit, because the user chose not to use
independent review for this build. Commits made directly by the agent do not
carry worker trailers, so `scripts/verify-candidate-commits.py` does not apply to
them.

## 2026-11-04 — MB-009 accepted with one known limitation

The user accepted MB-009 candidate `e8d6c3c`. Eight of its nine recorded findings
are resolved. The F006 residual (latest-attempt authority held only in memory) is
recorded `separately-scoped` and linked to issue #55; MB-015 resolves it.

## 2026-11-04 — Process tooling parked; lessons moved into the product

MB-024 to MB-029 are `parked`. MB-025's candidate is preserved on its branch;
MB-023 shipped. The lessons they encoded are now Milburn requirements: PRD
sections 12.4 to 12.7, acceptance criteria 27 to 31, ARCH 5.17, and added
acceptance criteria on MB-013, MB-014, MB-015, MB-016, MB-019, and MB-021.
v1 stays Codex-only; multi-harness lessons are recorded under deferred work.
