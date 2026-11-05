# Single-agent build procedure

## Stopped: no tasks until the rewritten PRD and ARCH are approved

As of 2026-11-04 the build is stopped after MB-013 (PR #63, merge `6db08eb`). The
product direction changed, and `PRD.md` and `ARCH.md` are being rewritten for user
review. Until the user approves the rewrite and replaces this section:

- Start no task. MB-014, MB-015, MB-016, MB-019, and MB-021 wait for the rewrite,
  which re-scopes them.
- Make no edits, branches, or pull requests for build tasks.
- If you were started to build, report this section to the user and stop.

The procedure below is kept for when the build resumes; it does not apply now.

One agent finishes the remaining core Milburn tasks alone. The coordinator and
worker model is suspended, not deleted: no coordinator session, no worker
worktrees or identities, no commit trailers, no plan-amendment freeze, no
AMEND-003 scripts, and no subagents other than the review subagent. Everything the agent needs is in this file, `tasks.json`,
`PRD.md`, `ARCH.md`, and `AGENTS.md` (Safety boundaries and testing rules still
apply).

## Scope and order

Suspended (see "Stopped" above). When resumed: build these tasks in order. A task
starts only when its dependencies are `done`.

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
request per task. Do not use the coordinator procedure in AGENTS.md. Launch
subagents only as the fresh-context gpt-6-sol reviewer that bootstrap/SINGLE_AGENT.md
requires for each task.
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
7. Independent review (below) before opening the pull request.
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

## Independent review (fresh-context `gpt-6-sol` subagent)

The author shares its own blind spots, and in this project's history nearly every
blocking defect was found by a reviewer, not by the builder's tests. So every task
is reviewed by a separate subagent that starts with no conversation history. This
is the only use of subagents in this build.

Spawn the reviewer after the task's tests pass and your own checks are done, before
the pull request:

- **Spawn settings:** model `gpt-6-sol`, medium reasoning effort, `fork_turns: none`
  (no inherited history). Fail closed: if the subagent tool or that model is not
  available, **stop and ask me**. Never fall back to reviewing your own work
  silently, and never spawn the reviewer with another model.
- **Read-only.** The reviewer may not edit files, commit, push, open or update pull
  requests, or merge. It returns findings only.
- **The reviewer brief** (write it to `bootstrap/progress/tasks/<task-id>-review-<n>.md`
  or pass it as the launch message) contains: task ID, title, and issue number; the
  acceptance criteria; the base and candidate commits (`git diff main...HEAD`);
  the PRD and ARCH sections the task cites, by file and line range; the six
  boundary questions; and the required test commands. Label anything you say about
  your own work as a *claim*, not as evidence, and do not paste your transcript or
  your reasoning.
- **What the reviewer must do:** read the diff against the acceptance criteria;
  for every validator and guard, name the weaker inputs that would pass it and
  check a test rejects them; for every fake, check parity with the real boundary;
  **enumerate every occurrence of each defect class on the first pass**, not just
  the first instance; run the tests with `scripts/run-tests.sh`.
- **What it returns:** a list of findings, each with an ID, the boundary-question
  number it violates (or the acceptance criterion), file and symbol, severity
  (`blocking` or `meaningful`), and the round; or an explicit statement that it
  found none.

Rounds:

1. **Round 1** is a full, exhaustive review of the whole diff.
2. For each blocking finding, **fix it**, add the regression test, and enumerate
   the class yourself before moving on.
3. **Re-review** with a **new** fresh subagent (not the previous one), giving it
   the prior findings and the fix commit range. It reviews the fixes and their
   blast radius first.
4. When a round comes back clean, run **one full confirmation pass** on the final
   diff with another fresh subagent.
5. **Stop and ask me** when a round has no fewer blocking findings than the last
   round that had findings, when a finding recurs (same boundary question, file,
   and symbol as one already fixed), when a fix adds a new blocking finding in code
   it touched, or after three fix rounds.

Record each round's findings in the progress file, and record every blocking
finding in `bootstrap/feedback/<task-id>.md` using the format in
`bootstrap/feedback/README.md`; run `python3 bootstrap/feedback/validate.py`. The
pull request lists the reviewer model, the rounds, and the findings. A finding the
user explicitly accepts stays open as deferred with a linked follow-up issue; you
never accept one yourself.

## Landing

- One pull request per task. Body: summary, acceptance-criterion evidence, test
  commands and results, the reviewer model with its rounds and findings, known risks, and
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
- The convergence limit in Independent review, or the reviewer subagent or its model
  being unavailable.
- Anything that would change the architecture or the product scope.

When every task in the table is `done`, update `bootstrap/progress/coordinator.md`
with a short completion record and stop.
