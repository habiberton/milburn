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

The root may parallelize `MB-010` and `MB-011` after their dependencies are
done. `MB-012` follows the Architect contracts, and `MB-013` follows issue
registry integration.

### Wave 4 — QA and recovery

After a complete Coder candidate path exists:

- `MB-014` — independent Tester and QA state transitions.
- `MB-015` — supervision, reconciliation, crash recovery, and fault handling.

These may run in parallel only if their owned paths remain separate.

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
centrally. Integrate one candidate at a time and run the combined smoke test
after each integration. Workers and reviewers never push; only the root
coordinator may push.

After integration, independent review, and every required test pass, the root
pushes `main` to `origin` and reads `origin/main` back to verify that it contains
the recorded task completion commit. Only after that remote verification may
the root apply `milburn:done` and close the task's GitHub issue.

## Retirement gate

Archive this bootstrap layer only after Milburn has demonstrated durable task
state, verified tmux lifecycle, Codex result collection, a persistent
Coordinator, one-task-per-Coder enforcement, progress-file recovery, and
independent Tester validation.
