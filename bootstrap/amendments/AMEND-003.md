# AMEND-003 — Scripted integration, context briefs, and root rotation

## Authority

- Source: direct user instructions in a Claude Code analysis session on 2026-11-04: write up the scripted integration design as an amendment proposal, then add context briefs with `fork_turns: none`, root session rotation, reviewer model assignment, defect-prevention rules, boundary questions, a reconcile command, quiet output, and a token report, and keep all changes in this one amendment. The user withdrew path/diff-based review tiering (a planner step will later assign risk scores) and chose to leave `tasks.json` as is. Not yet authorized for application.
- Authorized task: draft only; adoption requires explicit user approval and the plan-amendment gate (independent review, remotely merged PR, remote read-back, primary-checkout reconciliation).
- Motivation: session-log analysis showed the root coordinator consumed about 50% of all input tokens (172.8M of 346M), largely re-reading context while running the 18-step root integration procedure by hand and committing about 253 BOOTSTRAP bookkeeping commits. Subagent spawn calls
  in the root log show 27 of 58 spawns used `fork_turns: all`; the 25 matching
  session files (spawn calls and session files do not map one to one) consumed 142.4M of the 171.4M subagent input tokens (average first
  call 155k tokens, versus 21k for `fork_turns: none` sessions).

## Requested change

Replace the manual mechanical parts of the Root integration procedure with
`scripts/integrate-candidate.sh` (Python implementation behind a shell wrapper)
with subcommands `prepare`, `land`, `status`, and `record-review`. Step numbers
below refer to the 18-step Root integration procedure in `AGENTS.md`.

- `prepare <task> <attempt> <sha>` covers steps 1-4, 8, and 10: preflight,
  candidate and trailer verification, owned-path check, task tests plus
  `smoke-test.sh`, non-squash merge into the integration branch, then one
  registry/progress commit and a short report.
- `land <task> <attempt>` covers the mechanics of steps 11-18: gate checks (review
  verdict recorded, feedback validation, integration SHA unchanged), re-run
  tests, push the integration branch only, generate the PR body from records,
  merge with a merge commit, verify `origin/main` contains it, fast-forward the
  primary checkout, write final registry/progress records in one commit, and
  apply labels. Like the current process, the post-merge record commit stays
  on the local primary checkout and reaches `origin` inside the next ticket's
  integration branch and PR; the script never pushes it to `main`.
- The script commits its own registry and progress updates (two commits per
  task: after `prepare`, after `land`) under the configured coordinator
  identity. It runs `validate.py --preflight` before committing and restores
  the touched files on failure.
- `record-review <task> <attempt> <mode> <verdict>` stores the review mode, its
  risk reason, the verdict, and that round's findings in the task record so
  `land` can check them without reading prose. Each finding records an ID, the
  boundary-question number it violates, the file and symbol, severity, and
  round; this is also what the convergence rule below reads.
- Judgment steps stay with the root: path exceptions (5), feedback briefs (6),
  acceptance-evidence sufficiency (7), interface compatibility and review-mode
  selection (9), and the independent review itself.
- Review-mode selection: unchanged from AMEND-002 and the existing risk-based
  policy in `AGENTS.md`. The root selects and records the review mode and its
  risk reason; the integration script requires a recorded mode and review
  verdict before `land`, and logs the mode. This amendment adds no path-based,
  diff-based, or tag-based tiering. A future planner step is expected to attach a
  risk score to each task, and a later amendment will make review selection
  consume it. Rework follows a convergence rule, not a fixed count (see
  "Review rounds and escalation" below). (Supersedes the earlier diff-based tiering proposal, which the user withdrew
  in favor of planner-assigned risk scores. The script committing its own
  registry and progress updates remains confirmed.)

Review rounds and escalation:

- Round 1 is a full, exhaustive review. Each later round is a delta re-review of
  the fix and its blast radius. When a round is clean, one full-pass
  confirmation runs on the final SHA. The confirmation is itself a round.
- Automatic rounds continue only while the work is converging. A round's
  count is its number of blocking findings. The task goes to the user, with the
  stuck reason recorded, when any of these holds:
  1. A finding recurs: it matches an earlier finding recorded as fixed, by the
     same boundary-question number and the same file and symbol.
  2. The round has no fewer blocking findings than the most recent earlier round
     that had findings. (A clean round followed by a confirmation pass that finds
     issues is compared with the last round that had findings.)
  3. The round introduces a new blocking finding in code the previous fix
     touched.
  4. Three fix rounds have already been run (hard backstop).
- `integrate-candidate.sh record-review` computes the result (`continue` or
  `escalate` with the triggering rule) from the recorded findings. The root may
  escalate earlier but may not continue past an `escalate` result or the
  backstop.
- Escalation records a concrete blocker for that task in `state.md` and
  `coordinator.md` and pauses only that task's path; other ready work continues
  under the existing continuation gate.
- Baseline for tuning: with re-review rounds as a rough proxy, 6 of the 13
  recorded tasks needed three or more fix rounds and 9 needed two or more. The
  backstop and rules are expected to be revisited from measured data after the
  first tasks run under them.

Context briefs (replace whole-repository startup reads):

- `scripts/make-brief.py` is the only writer of generated briefs and derives
  them from `tasks.json`, progress files, and Git state.
- Worker brief at `bootstrap/briefs/<task>-<attempt>.md` (target about 2k
  tokens): task ID, title, attempt, worktree, branch, exact base SHA, owned and
  prohibited paths, Git identity, acceptance criteria, required tests, line
  ranges or extracted excerpts of only the referenced PRD and ARCH sections, a
  short worker-rules block, and on resume a summary of the task progress file.
  Workers read the brief and the files it points to, not the full `AGENTS.md`.
- Reviewer brief at `bootstrap/briefs/<task>-<attempt>-review-<n>.md`: the task
  record fields above, the base and candidate (or integrated) SHAs, the recorded
  review mode, the boundary questions, and for a re-review the prior findings
  and the fix commit range so the delta review can start from them.
- Root state digest at `bootstrap/progress/state.md` (capped at about 80
  lines): current wave, preflight result, task status table, active workers
  with branch, worktree, base and candidate SHAs, review status,
  dependency-ready tasks, blockers, and the resume action. Completed history
  moves from `coordinator.md` to `bootstrap/progress/history/`, read on demand.
  `tasks.json` itself keeps its current schema and content for now; the root
  reads task records through briefs and `state.md` instead of whole-file reads.
- Briefs embed a source digest. A smoke-test check fails when a brief or digest
  is stale relative to the registry, and briefs point to authoritative sources
  rather than restating specifications.
- Spawn policy: every worker and reviewer is spawned with `fork_turns: none`
  and a launch message that points to its brief. `fork_turns: all` is not used
  for workers or reviewers. Replacement and resumed sessions are started from
  the brief and handoff manifest, not from inherited transcript.

Root session rotation (replaces reliance on auto-compaction):

- Evidence: the root session ran as one 3.6-hour turn with three compactions
  (summaries of 152-174KB, restarting at 45-57k tokens). A fresh root reading
  `bootstrap/progress/state.md` starts near 20k tokens.
- Trigger: rotate at the first quiescent point after context use reaches a
  configured percentage of the model's context window (initial value 35%) or an
  absolute token ceiling (initial value 100k), whichever comes first. Both
  values live in `bootstrap/config.json` (also the home of the model IDs below)
  so the rule applies across models. The
  percentage controls compaction risk; the absolute ceiling bounds per-call
  cost on large-window models. The implementation must verify that the root can
  observe its own context usage in-session; otherwise the launcher supplies it.
- Quiescent point: the coordinator planning files are committed,
  `validate.py --preflight` is clean, no judgment step is half-done (an
  unrecorded review verdict or a partly written feedback brief), and the
  integration script is between phases (`status` reports the phase).
- Workers in flight: until a live test shows workers survive a root session
  ending, rotation happens only when no worker or reviewer is running (drain
  then rotate). In the observed run there were 13 gaps with no subagent running
  (8 of at least 2 minutes, about 20% of the span). If workers are shown to
  survive, rotation may occur with workers running, and the new root
  re-attaches them from `state.md`.
- Checkpoint: before rotating the root writes `state.md` (in-flight workers,
  what each is awaited for, pending decisions, resume action), commits it, and
  stops with rotation as the stated reason.
- Stop condition: `AGENTS.md` and `ROOT_PROMPT.md` add "rotation requested at a
  quiescent point with a valid checkpoint" as a permitted stop, alongside the
  existing stop reasons.
- Launcher: `scripts/run-root.sh` starts each root session as a fresh
  `codex exec` run with the `ROOT_PROMPT.md` block (user-supplied information
  that `codex exec` runs non-interactively; not independently verified against
  the Codex documentation). After each run it checks `state.md` and the
  reconcile result: it relaunches fresh when rotation was requested, and stops
  on a recorded blocker, an escalation, no remaining authorized work, or a
  configured maximum number of rotations. `codex exec resume` is reserved for
  crash recovery and is not used for rotation, because resuming restores the old
  context. `--ephemeral` is not used, because the token report reads the
  rollout files.
- Launcher permissions: non-interactive runs need credentials and predetermined
  sandbox and approval settings. The values are a user decision recorded in
  `bootstrap/config.json`; this amendment does not choose them. The original
  root session ran with approval policy `never` and a full-access sandbox.
- Still unverified: whether subagent tools are available in `codex exec` runs
  and whether workers survive a root session ending (see above).

Model assignment (initial, hardcoded in `bootstrap/config.json`):

- Root coordinator: `gpt-5.6-sol`. Builders (coders): `gpt-5.6-sol`, unchanged
  from the observed baseline (all 56 subagent sessions inherited
  `gpt-5.6-sol` at medium effort).
- Reviewers (Specification, Standards, Focused, re-reviews, and finals):
  `gpt-6-sol`, a different and higher-capacity model than the builder so that
  review does not share the builder's blind spots.
- Reasoning effort is unchanged (medium) until a later amendment sets it.
- `bootstrap/config.json` is the single place model IDs appear. If a configured model
  is unavailable at spawn time, the spawn fails closed with a logged reason; it
  must not silently inherit the root's model. The implementation must verify
  the exact IDs against the spawn tool's available model list.
- Each session's model, effort, role, review mode, and outcome are logged so a later
  amendment can tune assignment from pass rates.
- Out of scope for this amendment: cheaper first-attempt models and model
  escalation after failed rounds. (The convergence rule above is a process limit
  that does not depend on model choice.)

Defect-prevention rules (from the 38 recorded findings in MB-001 to MB-022
excluding MB-009: 37 blocking and 37 found in review; by the author's
categorization 18 were validation that accepted too much, 8 identity or replay
keying, 4 fake/live parity gaps, 4 failure or retry paths):

- Negative tests: acceptance criteria for any validator or adapter must
  require negative tests, written before the happy path.
- Exhaustive first review: reviewers must enumerate the whole class of a
  defect on the first pass, listing every place a pattern appears (for example
  every `required` set or every identity key), not just the first instance.
- Fake/live parity: any fake adapter must ship with fake/live parity tests that
  cover every lifecycle operation and terminal state the live adapter supports.
- Delta re-review: after a fix, the re-review covers the fix and its blast
  radius first. A full pass is run only once, at the end, on the final SHA. Rounds
  continue or escalate under "Review rounds and escalation" below.

Boundary questions (generic, shared by builders and reviewers):

- Source: the recorded review findings fall into a few recurring categories.
  Validation that accepted too much appeared in 9 unrelated tasks; identity or
  replay keying in 3 event and replay tasks; fake/live parity gaps wherever a
  fake adapter was written. The questions below are phrased about boundaries
  and name no specific task.
- Every worker brief includes all six questions, and the builder applies those
  that fit the task:
  1. For every check you write: what could pass this check while the real
     condition is false? Add a test where that happens.
  2. For every input or record you accept: list each field and variant, then
     either validate it or state that you ignore it.
  3. For every public entry point: can a caller bypass the guard?
  4. For every identifier used as a key: is it unique across the whole scope
     where it is used?
  5. For every state change or external effect: are preconditions checked
     before the change, and does every failure path leave state consistent?
  6. For a fake or test double: does it enforce the same preconditions and
     terminal states as the real implementation?
- Reviewers use the same questions: a finding cites the question number it
  violates, and the exhaustive-first-review rule lists every place the pattern
  appears. Each new finding is categorized against these questions so their
  effect can be measured after the first few tasks.
- `make-brief.py` may append, as examples under the matching question, the
  Lesson lines from feedback briefs of earlier tasks. Tailoring which
  questions a task receives is left to the future planner risk score.

Reconcile command (startup and continuation gate):

- `scripts/reconcile.sh` (Python implementation behind a shell wrapper) compares `tasks.json` with
  GitHub issue assignment and lifecycle labels, worktrees and branches,
  progress files, pending candidates, coordinator pull requests, local and
  remote Git state, dependency-ready tasks, and `validate.py --preflight`. It
  prints a short result: pass or the list of mismatches, plus the dependency-
  ready tasks. Full detail goes to a log file.
- The root uses it for the `AGENTS.md` startup reconciliation step and for the
  continuation gate before every final response, replacing the many
  individual commands the root used to build that picture. The script reports;
  it does not fix mismatches or change state.
- The startup procedure reads `state.md` and the reconcile result, and reads
  the PRD, ARCH, and other specifications only in the sections a decision needs.

Quiet output rule:

- Test, smoke-test, preflight, and validator runs invoked by the root or by
  scripts print one line (command, result, duration, log path) and write full
  output to a log file under a gitignored directory. On failure they also print
  the relevant excerpt. Agents read the log only when the one-line result is
  not enough. This applies to `scripts/smoke-test.sh`, `pytest` runs, and
  `validate.py`, through a shared wrapper so the behavior is the same
  everywhere.

Token report:

- `scripts/token-report.py` reads session rollout logs and reports input,
  cached, and output tokens per session, role, task, and model, with spawn
  mode (`fork_turns`), call counts, and compaction counts. Its output is the
  before-and-after measure for this amendment: baseline from the 58 sessions
  analyzed (346M input tokens, 99% cached; root 172.8M; forked subagents
  142.4M), compared after the first tasks run under the new rules. It reads
  logs only and never changes repo state.
- Reviewer cost note: reviewers used about 20% of input tokens at the baseline,
  and the move to `gpt-6-sol` for reviewers is expected to raise that share
  until risk-based review selection returns. The report tracks review tokens
  separately so the effect is visible.

Safety constraints: never push to `main` directly (commits on the primary checkout stay local and reach `origin` only through a coordinator PR); never override
the configured Git identity; never commit on a failed check; idempotent and
resumable; refuse ambiguous states. The script requires its own tests using a
throwaway repository and a stubbed `gh` before first use on a real task.

## Affected tasks

- New implementation tasks, each with tests, to be added to
  `bootstrap/tasks.json` after approval: the integration script, the brief
  generator, the reconcile command, the quiet-output wrapper, the root launcher, and the
  token report (owned paths: `scripts/`, `tests/bootstrap/`, `bootstrap/briefs/`, plus
  `bootstrap/config.json` and the `.gitignore` entry for the log directory,
  which the coordinator assigns to one task).
  The coordinator may group these into fewer tasks when owned paths do not
  overlap.
- All future tasks follow the revised procedure once effective.
- Completed task history remains unchanged.

## Active-work impact

| Work | Classification | Review decision |
|---|---|---|
| MB-009 candidate integration | unaffected | Finishes under the current manual procedure. |
| Any other active attempt | unaffected | Continue with the same ownership and generation. |

This record is committed on the unmerged branch
`bootstrap/coordinator/AMEND-003/a01-amendment`, so it does not freeze dispatch
on `main` until it is merged or copied into the primary checkout. Once present
there, `Dispatch status: frozen` applies until the amendment is reconciled. No
active attempt changes branch, worktree, or ownership.

## Registry and specification changes

- Registry changes: add the integration-script, brief-generator, reconcile, quiet-output, root-launcher, and token-report tasks; `tasks.json` schema and finished-task records unchanged; no risk tags are added to tasks; none applied by this draft.
- Specification changes: `AGENTS.md` Root integration procedure, risk-based review, startup procedure, worker launch brief, spawn policy, model assignment, review and acceptance-criteria rules, continuation gate, and stop-condition sections, and `bootstrap/README.md` and `bootstrap/ROOT_PROMPT.md`, to describe the script, review-mode recording, the rework cap, briefs, the reconcile command, quiet output, and `fork_turns: none`; PRD and ARCH unchanged. New or moved files: `scripts/run-root.sh`, `scripts/reconcile.sh`, `scripts/token-report.py`, a shared test-output wrapper, a gitignored log directory, `bootstrap/config.json`, `scripts/make-brief.py`, `bootstrap/briefs/`, `bootstrap/progress/state.md`, `bootstrap/progress/history/`.
- GitHub changes: none by this draft.

## Effectiveness

- Planning commit: pending
- Effective remote PR: pending
- Effective merge commit: pending
- Dispatch status: frozen
- Resolution status: pending
