# Milburn bootstrap instructions

This repository is building Milburn, a local control plane for coordinating
long-running Codex agents. Until Milburn can coordinate its own development,
the root Codex agent acts as the temporary bootstrap coordinator.

The product and architecture decisions in `PRD.md` and `ARCH.md` are approved
inputs. Do not run an architecture review, propose a replacement architecture,
or ask subagents to redesign the system. If implementation exposes a direct
contradiction or an impossible requirement, record it as a blocker and ask the
user. Otherwise, implement the approved design.

## Sources of truth

Read these files before changing code:

1. `PRD.md` — approved product behavior and scope.
2. `ARCH.md` — approved architecture and authority boundaries.
3. `bootstrap/README.md` — bootstrap workflow and work waves.
4. `bootstrap/tasks.json` — implementation tasks, dependencies, ownership, and
   acceptance criteria.
5. `bootstrap/progress/coordinator.md` — current integration state.
6. `bootstrap/decisions.md` — settled bootstrap decisions.

If these sources conflict, stop the affected work, record the conflict, and ask
the user. Do not silently choose one.

## Root coordinator and workers

The agent launched by the user in the primary checkout is the root bootstrap
coordinator. It owns task selection, task-registry updates, worktree creation,
subagent dispatch, integration, and completion decisions.

A subagent assigned a task is a worker. Workers must not launch additional
subagents. If subagent tools are unavailable, the coordinator follows the same
task process sequentially; it must not imitate delegation with unmanaged
background processes.

Only the root coordinator may update:

- `bootstrap/tasks.json`
- `bootstrap/progress/coordinator.md`
- shared specifications or shared interface decisions
- the primary integration checkout

Each worker updates only its assigned task progress file under
`bootstrap/progress/tasks/`.

## Startup procedure

At the beginning of every new or resumed root session:

1. Confirm this is the Milburn repository and `.git/` exists.
2. Read this file and `bootstrap/README.md` completely.
3. Read `PRD.md`, `ARCH.md`, `bootstrap/tasks.json`,
   `bootstrap/progress/coordinator.md`, and `bootstrap/decisions.md`.
4. Inspect `git status` and recent Git history.
5. Run `scripts/smoke-test.sh`.
6. Reconcile task records with branches, worktrees, commits, progress files,
   and tests.
7. Continue the active wave from `bootstrap/tasks.json`.

Do not spend a startup turn reassessing the approved product or architecture.
The executable task graph and work waves have already been provided.

## Work-wave rules

Follow the waves in `bootstrap/README.md` and `bootstrap/tasks.json`.

- Complete foundation tasks sequentially.
- Parallelize only ready tasks in the current wave.
- Do not start a later wave merely because one task in the current wave is
  blocked.
- Use no more than three implementation workers concurrently.
- Prefer two workers until shared contracts and test conventions are stable.
- Integrate and verify each candidate separately.

The coordinator may split an oversized task into smaller implementation tasks
without changing product behavior or architectural ownership. Record any split
in `bootstrap/tasks.json` before dispatch. Do not recombine or redesign the
approved components.

## Parallel delegation gate

Tasks may run concurrently only when all of the following are true:

- Every dependency is `done`.
- Required public interfaces are already present on the integration branch.
- Workers do not own the same files or directories.
- Workers do not modify the same schema, migration, configuration, generated
  artifact, or shared fixture.
- Neither task needs the other task's unfinished implementation.
- Each task has independent acceptance criteria and tests.
- Each task can produce a reviewable commit without merging another worker's
  branch.

If these conditions are not met, run the tasks sequentially.

## Worktree preparation

The root coordinator creates every worker worktree before launching its worker.
Use:

- Branch: `bootstrap/<role>/<task-id>/<attempt-id>-<short-name>`
- Worktree: `../milburn-worktrees/<task-id>-<attempt-id>`

Before dispatch, update the task record with:

- owner
- branch
- absolute worktree path
- base commit
- owned paths
- progress-file path

Create the task progress file from
`bootstrap/progress/tasks/TEMPLATE.md` before creating the worker branch, so it
is present in the worker's starting commit.

After creating the worktree and before launching the worker, configure its
logical Git identity:

```text
scripts/configure-worktree-identity.sh \
  <absolute-worktree> <role> <task-id> <attempt-id>
```

The script uses the repository's approved GitHub-linked email without writing
that email into tracked files. It assigns a distinct name such as
`Milburn Builder [MB-005/a01]` and records the role, task, attempt, and worker ID
in worktree-local Git configuration.

The primary checkout is reserved for coordination and integration. Workers must
not edit it.

## Worker launch brief

Every worker receives:

1. Task ID and title.
2. Absolute worktree path.
3. Exact base commit.
4. Relevant PRD and ARCH sections.
5. Owned and prohibited paths.
6. Acceptance criteria.
7. Required test commands.
8. Progress-file path.
9. Configured Git identity and attempt ID.
10. Instruction to create commits with `scripts/agent-commit.sh`.
11. Instruction to return a candidate commit rather than merge it.

Every worker begins by reading `AGENTS.md`, its task record, relevant approved
specification sections, Git status, relevant Git history, and its progress file.

## Worker rules

A worker must:

- Work only in its assigned worktree and on its assigned task.
- Stay within owned paths unless the coordinator approves an expansion.
- Record shared-interface needs as blockers instead of changing shared
  contracts independently.
- Implement one small vertical slice at a time.
- Test behavior through public interfaces.
- Update its progress file after meaningful checkpoints and before handoff.
- Stage intended changes and create coherent commits with
  `scripts/agent-commit.sh "<summary>"`. The helper adds the task prefix and
  required role, worker, task, and attempt trailers.
- Return the exact candidate commit SHA and test evidence.
- Stop after producing the candidate.

A worker must not:

- Update `bootstrap/tasks.json` or coordinator progress.
- Modify another task's progress file.
- Change `PRD.md` or `ARCH.md`.
- Merge, rebase, or cherry-pick another worker's work.
- Mark its own task complete.
- Launch another agent.
- Integrate into the primary branch.
- Push any branch or commit to a remote.

## Root integration procedure

When a worker returns a candidate:

1. Confirm the commit exists on the assigned branch.
2. Verify every candidate commit before review or integration:

   ```text
   scripts/verify-candidate-commits.py \
     <base-sha> <candidate-sha> <role> <task-id> <attempt-id>
   ```

3. Read the task progress record.
4. Compare the diff with owned paths.
5. Reject or explicitly review unapproved path changes.
6. Check every acceptance criterion against evidence.
7. Run the task tests independently.
8. Review compatibility with approved shared interfaces.
9. Integrate one candidate at a time with a non-squash merge so worker commit
   attribution remains intact.
10. Run `scripts/smoke-test.sh` after every integration.
11. Record the integrated commit and result in the task registry and
    coordinator progress.
12. Confirm the independent review passed and every required test is green.
13. The root coordinator pushes `main` to `origin`; no worker or reviewer may
    push.
14. Fetch or query `origin/main` and verify that it contains the recorded task
    completion commit. A successful push command without this read-back is not
    completion evidence.
15. Only after remote verification may the root apply `milburn:done` and close
    the GitHub issue.

Do not delete a worktree until its candidate is integrated, rejected, or
explicitly archived.

## Independent review procedure

Before marking an integrated task `done`, the coordinator launches a separate
review subagent when subagent tools are available. The reviewer receives the
task record, approved specification sections, base commit, and candidate or
integrated commit. It reviews two questions separately:

1. Does the change satisfy every task acceptance criterion and the approved
   specification?
2. Does the change preserve repository conventions, public interfaces,
   maintainability, and test quality?

The reviewer does not modify the candidate branch or push any branch or commit.
It returns findings with file locations and evidence. The coordinator either
records a pass or returns the same task to a worker with the findings. When
subagent tools are unavailable, the root performs a distinct review pass after
clearing the implementation context as much as practical and records that
limitation.

## Conflict procedure

If workers discover that they need the same interface or file change:

1. Pause the affected tasks.
2. Record the conflict in coordinator progress.
3. Resolve the shared change centrally within the approved architecture.
4. Ask the user only if the resolution changes an approved product or
   architecture decision.
5. Update affected task bases before work resumes.

Do not allow workers to create competing shared interfaces.

## Completion and handoff

Workers produce candidate commits. The root coordinator integrates candidates.
A separate review pass supplies QA evidence. Only the root coordinator may
push. Only after integration, independent review, required tests, a successful
push of `main`, and verification that `origin/main` contains the completion
commit may the coordinator mark a task `done` and close its GitHub issue.

Before ending any session, record completed work, exact commits, test commands
and results, remaining work, blockers, and the first action for the next agent.
Process exit or a prose claim is never proof of completion.

## Safety boundaries

- Preserve user changes and unrelated work.
- Do not reset or destructively clean a checkout.
- Do not expose secrets in prompts, progress files, commits, logs, or fixtures.
- Do not replace or override the configured worktree Git identity.
- Do not merge, deploy, or mutate GitHub unless the current bootstrap task and
  the user explicitly authorize it.
- Worktrees provide change isolation, not a security sandbox.
