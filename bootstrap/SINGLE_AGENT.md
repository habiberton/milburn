# Single-agent build procedure

One agent finishes the remaining core Milburn tasks alone. The coordinator and
worker model is suspended, not deleted: no coordinator session, no worker
worktrees or identities, no commit trailers, no plan-amendment freeze, no
AMEND-003 scripts. Everything the agent needs is in this file, `tasks.json`,
`PRD.md`, `ARCH.md`, and `AGENTS.md` (Safety boundaries and testing rules still
apply).

## Scope and order

Build these tasks in order. A task starts only when its dependencies are `done`.

| Layer | Tasks | Notes |
|---|---|---|
| 1 | MB-010, MB-011 | MB-009 is already accepted (PR #56); either order |
| 2 | MB-012 | needs MB-011 |
| 3 | MB-013 | needs MB-009, MB-012 |
| 4 | MB-014, MB-019 | either order |
| 5 | MB-015, MB-021 | MB-015 also resolves issue #55 (MB-009 finding F006) |
| 6 | MB-016 | reference workflow, docs, acceptance proof |

Parked, not part of this build: MB-024 to MB-029 (process tooling for the
coordinator model). MB-025's candidate stays on branch
`bootstrap/builder/MB-025/a01-bootstrap-config`. MB-023 is done.

The PRD gained requirements 12.4 to 12.7 and acceptance criteria 27 to 31. Their
acceptance criteria were added to MB-013, MB-014, MB-015, MB-016, MB-019, and
MB-021. Build them as part of those tasks.

## Start prompt

```text
You are the single build agent for Milburn. Read bootstrap/SINGLE_AGENT.md first
and follow it exactly. PRD.md and ARCH.md are approved; do not redesign them. If
they contradict each other or a requirement is impossible, stop and ask me.

Work through the tasks in the order given there, one task at a time, one pull
request per task. Do not use the coordinator procedure in AGENTS.md. Do not
launch subagents.
```

## First actions (once)

1. `git status`, `git fetch`, and confirm `main` matches `origin/main` and is clean.
2. Run `python3 bootstrap/amendments/validate.py --preflight` and
   `scripts/smoke-test.sh`. Both must pass before you start.
3. Check that PR #56 (MB-009) is merged. If not, stop and tell me.
4. Fix stale records: add the `milburn:done` label (and remove
   `milburn:decision-needed`) on issue #9; backfill MB-009's `pull_request`
   merge commit in `tasks.json`.

## Per-task loop

1. Read the task record with a script that prints only that task (do not read
   all of `tasks.json`). Read only the PRD and ARCH sections it needs.
2. Create a branch `product/<task-id>-<short-name>` from up-to-date `main`.
   Set the task `in_progress` in `tasks.json` and the GitHub label to
   `milburn:in-progress`.
3. Keep a progress file at `bootstrap/progress/tasks/<task-id>.md` (copy
   `TEMPLATE.md`). Update it at each checkpoint, with a `Resume here` section.
4. Build in small vertical slices. Owned paths are guidance: you may add files in
   the same directories, and say so in the pull request.
5. Rules while building:
   - Negative tests first for every validator, guard, and adapter, then the happy path.
   - Apply the six boundary questions below to every boundary you touch.
   - A fake must enforce the same preconditions and terminal states as the real
     thing, with parity tests.
   - Test through public interfaces. Run tests with `scripts/run-tests.sh`; do
     not create your own virtualenv or set `PYTHONPATH`.
6. Commit coherent commits with the task prefix, for example
   `MB-010: add notification queue`. Normal `git commit`; no special trailers.
7. Self-review (below) before opening the pull request.
8. Open one PR per task (see Landing).

### Boundary questions

1. For every check you write: what could pass this check while the real condition
   is false? Add a test where that happens.
2. For every input or record you accept: list each field and variant, then either
   validate it or state that you ignore it.
3. For every public entry point: can a caller bypass the guard?
4. For every identifier used as a key: is it unique across the whole scope where
   it is used?
5. For every state change or external effect: are preconditions checked before
   the change, and does every failure path leave state consistent?
6. For a fake or test double: does it enforce the same preconditions and terminal
   states as the real implementation?

## Self-review (the same agent reviews its own work)

A review by the author shares the author's blind spots, so make it mechanical.
Do it after the task's tests pass, before the pull request:

1. **Checklist first.** Before rereading code, write into the progress file a
   checklist from the acceptance criteria, the six boundary questions, and the
   PRD and ARCH sections the task cites.
2. **Read the diff, not your memory.** Run `git diff main...HEAD` and go through
   it against the checklist, item by item. For each validator or guard, write the
   weaker inputs that would pass it and confirm a test rejects each. For each
   fake, list the parity cases.
3. **Enumerate the class.** For every defect you find, search for every other
   place the same pattern occurs and list them all before fixing any.
4. **Record findings** in the progress file: ID, boundary-question number, file
   and symbol, severity (blocking or meaningful), round.
5. **Fix, then review the fix and its blast radius**, then do one full pass on
   the final diff.
6. **Stop and ask me** when a round has no fewer blocking findings than the last
   round that had findings, when a finding recurs, when a fix adds a new blocking
   finding in code it touched, or after three fix rounds.

Record every blocking finding you fixed in `bootstrap/feedback/<task-id>.md`
using the format in `bootstrap/feedback/README.md`, and run
`python3 bootstrap/feedback/validate.py`. The pull request states that review
was by the same agent. I can ask for an independent review at any time.

## Landing

- One pull request per task. Body: summary, acceptance-criterion evidence, test
  commands and results, self-review findings and rounds, known risks, and
  `Closes #<issue>`.
- Before opening it: `scripts/smoke-test.sh` passes, `git diff --check` is clean,
  `python3 bootstrap/amendments/validate.py` passes, and `tasks.json` marks the
  task `done` with its PR number.
- Merge authority: you merge your own pull request with a **merge commit**
  (`gh pr merge --merge`) once the checks above pass. Never squash or
  rebase-merge, and never push to `main`. To require my approval instead, I will
  delete this bullet and you will stop at "PR open".
- After the merge: fetch, confirm `origin/main` contains the merge commit,
  fast-forward local `main`, set the GitHub label to `milburn:done`, and fill in
  the merge commit in `tasks.json` in the next task's branch.

## Session hygiene

- Commit after each task. If the context is getting large (about 60% of the
  window), write `Resume here` in the progress file and say so; a fresh session
  can continue from this file, `tasks.json`, and `git log`.
- Prefer a fresh session per layer. Never read `tasks.json` or
  `bootstrap/progress/coordinator.md` whole; both are large.

## Stop and ask

- A contradiction between `PRD.md` and `ARCH.md`, or an impossible requirement.
- Missing credentials, permissions, or an action that mutates GitHub beyond issue
  labels, pull requests, and the task's own issue.
- The convergence limit in Self-review.
- Anything that would change the architecture or the product scope.

When every task in the table is `done`, update `bootstrap/progress/coordinator.md`
with a short completion record and stop.
