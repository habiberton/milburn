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
- `feedback/<task-id>.md`: one coordinator-owned concise defect brief per task;
  `feedback/README.md` defines its validated format and completion gates.
- `decisions.md`: bootstrap implementation decisions that do not change the
  approved product or architecture.
- Added by AMEND-003 as they are implemented: `progress/state.md` (short
  root-owned state digest), `briefs/` (generated worker and reviewer briefs),
  `config.json` (rotation thresholds and model IDs), and `progress/history/`
  (completed-work log moved out of `coordinator.md`). Generated files are
  written only by their scripts.

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
5. `MB-020` — temporary bootstrap defect-feedback briefs, validation, and
   backfill for MB-001 through MB-004.

These tasks are sequential because every later worker depends on their
interfaces, test conventions, and feedback process. `MB-020` uses its own
one-ticket coordinator branch and PR after MB-004; its implementation must not
be mixed into the MB-004 PR.

### Wave 2 — Independent boundaries, parallel

After Wave 1 including `MB-020` is integrated, dispatch independent boundary
implementations. `MB-005` through `MB-009` all depend on `MB-020`, so Wave 2
cannot begin before the feedback process exists:

- `MB-005` — tmux runtime and fake runtime.
- `MB-006` — Codex adapter, briefs, and result parsing.
- `MB-022` — durable bootstrap and product plan-amendment gates. It follows
  `MB-020` and must complete before any new MB-007, MB-008, MB-009, MB-017, or
  MB-018 worker dispatch.
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

MB-005 and MB-006 were already active when MB-022 was authorized and are the
recorded unaffected exception: they continue through review and PR integration.
No other Wave 2 implementation worker launches while the first amendment is
pending, while coordinator planning files are uncommitted, or before MB-020 and
MB-022 are remotely merged and reconciled.

### Plan-amendment gate

A user-authorized change to scope, policy, specifications, tasks, dependencies,
waves, acceptance criteria, or dispatch rules is a pending plan amendment. The
coordinator records its authority, requested change, affected tasks, active-work
classification, registry/spec/GitHub changes, effective commit and PR, and
resolution. Active work is classified as `unaffected`, `needs steering`,
`must pause`, or `must stop`; unaffected attempts retain ownership and continue.

New worker dispatch remains frozen until planning files are clean, the amended
registry and specifications agree, the amendment commit is reviewed and merged
remotely, and the primary checkout and amendment record are reconciled. Startup
and continuation preflights treat an unresolved amendment as a concrete dispatch
blocker, not as permission to stop unrelated unaffected work.

The root assigns the next stable `AMEND-<number>` before changing the plan and
uses `bootstrap/amendments/AMEND-001.md` as the complete record example. It runs
`python3 bootstrap/amendments/validate.py --preflight` at startup, before worker
dispatch, and before a final response. The preflight fails for an unresolved
record or uncommitted changes in AGENTS, PRD, ARCH, ROOT_PROMPT, the bootstrap
README, task registry, decisions, or amendment records. Smoke validation checks
record structure without requiring a clean worktree.

Every required record section contains section-scoped evidence. Active-work
rows use exactly `unaffected`, `needs_steering`, `must_pause`, or `must_stop`;
when no attempts are active, record `- No active work.` instead. Effectiveness
uses dispatch state `frozen`, `resumed`, or `unchanged` and resolution state
`pending`, `effective and reconciled`, or `rejected and reconciled`. A pending
record uses `pending` for commit/PR/merge evidence and must remain frozen.
Effective records use exact commit and PR references; an effective record whose
dispatch state is still `frozen` continues blocking preflight.

The durable product lifecycle is `requested → impact_assessed → approved |
rejected → applied → dispatch_resumed`. Request freezes dispatch before impact
assessment. Approval binds the expected planning revision plus specification,
registry, and GitHub-effect evidence. Application requires remote merge
evidence and primary-checkout reconciliation; replay and duplicate delivery are
idempotent. Rejection also requires an explicit dispatch-resumption fact.

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
- `MB-021` — durable defect observations, resolutions, regression evidence,
  replayable feedback projections, and completion gates. It follows `MB-003`
  and `MB-014`.
- `MB-019` — role-specific session continuation, rotation, and replacement
  policy. It follows `MB-010`, `MB-013`, `MB-017`, and `MB-018`.
- `MB-015` — supervision, reconciliation, crash recovery, and fault handling.

`MB-015` depends on `MB-019`, so supervision and recovery use the same fenced
replacement policy. `MB-016` remains transitively gated through `MB-015`.
Other Wave 4 work may run in parallel only if its owned paths remain separate.

### Wave 5 — Integrated proof

`MB-016` connects the complete workflow, runs scripted end-to-end scenarios,
adds protected live evaluations, completes operational documentation, and
proves the acceptance criteria in `PRD.md`. It depends on `MB-021` so final
operator views and acceptance evidence include defect feedback.

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

The root integrates verified worker commits without squashing, runs the selected
risk-based independent review mode and all required tests, then pushes the task
branch. Its evidence-bearing
PR records issue links, commit SHAs, attribution, acceptance evidence, test
results, selected review mode and reason, review findings, risks, a
`## Feedback summary` section with the task-brief link, and
`Closes #<issue-number>`. For a blocking or meaningful defect found during
review, test, integration, recovery, or production work, follow
`feedback/README.md`; workers propose entries in task progress and only the root
finalizes briefs. The root never pushes directly to `main` and merges the PR
only with a merge commit—never a squash or rebase merge.

### Risk-based review

All candidates receive coordinator attribution, owned-path and acceptance
checks, required tests, smoke tests, and PR evidence. Select and record two
independent passes—Specification and Standards—for contracts/state, persistence
or replay, process/tmux lifecycle, Codex or external adapters, GitHub/MCP
effects, recovery/session/amendment policy, security, shared interfaces, prior
blocking review findings, expanded scope, changed authority/dependencies, or
uncertain risk. MB-005 and MB-006 remain in this mode.

Select one Focused independent pass only for documentation, fixtures,
mechanical refactors, isolated tests, or comparably small changes without a
public interface, state transition, persistence, recovery, or external side
effect. It still covers applicable acceptance criteria, implementation quality,
tests, and risks. A blocking focused finding escalates the corrected candidate
to fresh Specification and Standards passes. Apply this policy prospectively;
do not rewrite completed task history.

After merging, the root fetches `origin/main`, verifies it contains the GitHub
PR merge commit, fast-forwards the primary checkout, and updates task records.
Only then, and after `scripts/smoke-test.sh` verifies the task feedback brief,
may it apply `milburn:done`, close an issue not already closed by the PR, and
begin the next task.

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
