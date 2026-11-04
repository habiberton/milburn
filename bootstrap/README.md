# Milburn bootstrap process

This directory is the temporary coordination layer used to build Milburn before
Milburn can coordinate itself. It implements the durable practices from the
long-running-agent design: bounded tasks, isolated worktrees, frequent progress
records, issue-linked commits, repeatable startup, independent review, and
recovery without a prior transcript.

The bootstrap layer is not the Milburn runtime. Product runtime state will
eventually live under `.milburn/`; bootstrap state remains under `bootstrap/`
and can be archived after self-hosting is proven.

## Approved inputs

`PRD.md` and `ARCH.md` are approved design inputs. The root agent translates
them into implementation and does not run a new architecture review. A direct
contradiction or impossible requirement is escalated to the user; ordinary
implementation choices remain within the approved design.

## Durable records

- `tasks.json`: root-owned dependency and recovery mirror. GitHub issues are the
  authoritative assignment and lifecycle-status registry after issue
  initialization; this file retains the dependency graph, owned paths, test
  commands, progress paths, and last-observed remote metadata.
- `progress/coordinator.md`: root-owned integration and recovery record.
- `progress/tasks/<task-id>.md`: one worker-owned record per active task.
- `decisions.md`: bootstrap implementation decisions that do not change the
  approved product or architecture.

## GitHub task registry

Every task in `tasks.json` is mirrored to one open `Task` issue in
`habiberton/milburn`. The issue's assignees are authoritative for assignment;
its open/closed state and Milburn lifecycle label are authoritative for status.
The stable marker `milburn:task-id=<task-id>` prevents duplicate creation.

The required labels are `milburn:task`, `milburn:ready`,
`milburn:in-progress`, `milburn:blocked`, `milburn:qa`,
`milburn:changes-requested`, `milburn:done`, and `milburn:decision-needed`.
Creating or reconciling issues does not launch implementation agents.

Git attribution is also durable. The bootstrap script configures the primary
checkout as `Milburn Coordinator [BOOTSTRAP/root]`. Every worker worktree gets
a unique role, task, and attempt identity, and every candidate commit carries
matching trailers that are verified before integration.

## Work waves

### Wave 0 — Bootstrap verification

The root agent verifies the repository, required files, task graph, current Git
state, and smoke test. This is not an architecture review. No product code is
delegated during this wave.

### Wave 1 — Foundation, sequential

Build shared foundations in order:

1. `MB-001` — package, CLI, configuration, and test foundation.
2. `MB-002` — domain contracts, commands, events, states, and errors.
3. `MB-003` — SQLite event store, expected sequence, projections, and replay.
4. `MB-004` — workflow controller shell and deterministic transition guard.

These tasks are sequential because every later worker depends on their
interfaces and test conventions.

### Wave 2 — Independent boundaries, parallel

After Wave 1 is integrated, dispatch independent boundary implementations:

- `MB-005` — tmux runtime and fake runtime.
- `MB-006` — Codex adapter, briefs, and result parsing.
- `MB-017` — observability-only Codex token usage events and replayable usage
  summaries. It depends on `MB-006` and must not run concurrently with
  unfinished `MB-006` work because it extends the adapter contract.
- `MB-018` — semantic session-generation observations and validated durable
  handoff manifests. It depends on `MB-006` and `MB-017` and must not run
  concurrently with unfinished work on either task because it extends both
  contracts.
- `MB-007` — skill catalog, role rules, validation, and digests.
- `MB-008` — GitHub gateway, MCP effect journal, and local fakes.
- `MB-009` — Git worktree manager and fake workspace manager.

Run no more than three workers concurrently. Begin with two. Each worker owns a
separate package surface and must use the shared Wave 1 contracts.

### Wave 3 — Coordination workflows

Integrate the boundaries into product workflows:

- `MB-010` — persistent Coordinator session, notifications, and decisions.
- `MB-011` — Planner, Classifier/Router, and Architect coordination.
- `MB-012` — GitHub issue registry and idempotent issue creation.
- `MB-013` — long-running Coder, issue assignment, progress, and candidate
  validation.

The root may parallelize `MB-010` and `MB-011` after their dependencies,
including `MB-017` and `MB-018`, are done. `MB-012` follows the Architect
contracts, and `MB-013` follows issue registry integration plus usage and
session-lifecycle telemetry.

### Wave 4 — QA and recovery

After a complete Coder candidate path exists:

- `MB-014` — independent Tester and QA state transitions.
- `MB-019` — role-specific session continuation, rotation, and replacement
  policy. It follows `MB-010`, `MB-013`, `MB-017`, and `MB-018`.
- `MB-015` — supervision, reconciliation, crash recovery, and fault handling.

`MB-015` depends on `MB-019`, so supervision and recovery use the same fenced
replacement policy. `MB-016` remains transitively gated through `MB-015`.
Other Wave 4 work may run in parallel only if its owned paths remain separate.

### Wave 5 — Integrated proof

`MB-016` connects the complete workflow, runs scripted end-to-end scenarios,
adds protected live evaluations, completes operational documentation, and
proves the acceptance criteria in `PRD.md`.

## Task lifecycle

```text
blocked → ready → assigned → in_progress → candidate → integrated → qa → done
                                  └──────────────→ blocked
```

Only the root coordinator changes task status. Workers report facts and
candidate commits through their own progress records.

## Worktree convention

```text
primary checkout: /path/to/milburn
worker branches:  bootstrap/builder/MB-005/a01-tmux-runtime
worker trees:     /path/to/milburn-worktrees/MB-005-a01
```

The root creates worktrees and passes their absolute paths to workers. Workers
never edit the primary checkout.

Immediately after creating a worker tree, the root runs:

```text
scripts/configure-worktree-identity.sh \
  /path/to/milburn-worktrees/MB-005-a01 builder MB-005 a01
```

The worker stages its changes and commits with:

```text
scripts/agent-commit.sh "implement verified tmux lifecycle"
```

Before integration, the root runs:

```text
scripts/verify-candidate-commits.py \
  <base-sha> <candidate-sha> builder MB-005 a01
```

## Integration rule

Decompose centrally, implement independent leaves in parallel, and integrate
centrally. One ticket has one coordinator-owned branch named
`bootstrap/coordinator/<task-id>/<attempt-id>-integration` and one pull request.
Later attempts update the same branch and PR. Workers and reviewers return local
commits and evidence only; they never push, open or update PRs, or merge.

The root integrates verified worker commits without squashing, runs independent
review and all required tests, then pushes the task branch. Its evidence-bearing
PR records issue links, commit SHAs, attribution, acceptance evidence, test
results, review findings, risks, and `Closes #<issue-number>`. The root never
pushes directly to `main` and merges the PR only with a merge commit—never a
squash or rebase merge.

After merging, the root fetches `origin/main`, verifies it contains the GitHub
PR merge commit, fast-forwards the primary checkout, and updates task records.
Only then may it apply `milburn:done`, close an issue not already closed by the
PR, and begin the next task.

## Continuation gate

Before any final response or handoff, reconcile `tasks.json`, GitHub issues,
active workers and worktrees, pending candidates and PRs, and every
dependency-ready task. Milestones are continuation points, not stopping points:
task completion, PR merge, issue closure, a newly ready task, any task count, a
completed wave, a returned candidate, or a committed policy/progress checkpoint
does not permit the root to stop.

Continue in the same turn whenever any task is `ready`, `assigned`,
`in_progress`, `candidate`, `integrated`, or `qa` and no genuine blocker
prevents progress. A completed wave flows into the next wave when its
dependencies are satisfied, subject to that wave's concurrency rules.

Stopping is permitted only for an explicit user stop/pause, a required user
decision or authorization, a blocker that prevents all safe progress, no
authorized unfinished work, or forced environment termination. Persist exact
recovery state before forced termination when possible. A final response is
prohibited while executable unblocked work exists; record a concrete blocker
for every unfinished path before stopping.

## Retirement gate

Archive this bootstrap layer only after Milburn has demonstrated durable task
state, verified tmux lifecycle, Codex result collection, a persistent
Coordinator, one-task-per-Coder enforcement, progress-file recovery, and
independent Tester validation.
