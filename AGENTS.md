# Building Milburn

Milburn is an agent distro: the user talks to one Coordinator, which dispatches role
agents into parallel Git worktrees and calls the `milburn` enforcement CLI. Use the
terms in `PRD.md` §2.

## Sources of truth

- `PRD.md` (what and why) and `ARCH.md` (how) are approved. Implement them; do not
  redesign them. If they contradict each other, or a requirement is impossible,
  stop that work and ask the user.
- The task list is the open GitHub issues labelled `milburn:task`. An issue's body
  and comments give its scope; the spec sections it cites are binding.
- `docs/reviews/` holds the review that produced the specs and the MB-030 gap list.

## Build order

Follow `ARCH.md` §15. As issues:

1. #67 harness adapter seam and Claude Code adapter
2. #16 walking skeleton (with the QA gate core from #14)
3. #72 cross-harness handoff
4. #68 delivery modes
5. #14 rest of the QA gate, #25 defect feedback
6. #15 reconcile and recovery, #23 and #44 rotation, briefs, digest, #42 usage sources
7. #69 stage tables and "Fix a bug", #70 OpenSpec and "Add a feature"
8. #71 retirements (a module may retire earlier once nothing uses it)
9. #62 live runs per harness pairing

Pick the first open issue whose dependencies are closed. Remove `milburn:blocked`
when you start it.

## Per-issue loop

1. Create a worktree from `origin/main`: branch `build/<issue>-<short-name>` at
   `../milburn-worktrees/<issue>-<short-name>`. Never edit `main` directly.
2. Write negative tests first for every validator, gate, adapter, and state change,
   then the happy path. Apply the boundary questions below.
3. A fake adapter ships with parity tests against the real one's lifecycle and
   terminal states, using recorded real runs where they exist.
4. Run `scripts/run-tests.sh -q`, `scripts/smoke-test.sh`, and `git diff --check`.
   Check exit codes. Never claim a pass you did not see.
5. Review by risk (PRD R38). Changes to state transitions, persistence, process
   lifecycle, harness adapters, GitHub effects, or security get an independent
   reviewer: a fresh-context subagent given the issue, the spec sections, and the
   base and head SHAs, never the builder's transcript. Fix blocking findings and
   re-review the fix. Docs and isolated test changes need no extra review.
6. Open one PR per issue with `Closes #<n>`, the spec sections implemented, test
   evidence, and review findings. Merge with a merge commit (never squash or rebase).
   Fetch and confirm `origin/main` contains the merge before starting the next issue.

### Boundary questions

1. For every check you write: what could pass this check while the real condition
   is false? Add a test where that happens.
2. For every input or record you accept: list each field and variant, then either
   validate it or state that you ignore it.
3. For every public entry point: can a caller bypass the guard?
4. For every identifier used as a key: is it unique across the whole scope where it
   is used?
5. For every state change or external effect: are preconditions checked before the
   change, and does every failure path leave state consistent?
6. For a fake or test double: does it enforce the same preconditions and terminal
   states as the real implementation?

## Tests and commands

- Run tests only through `scripts/run-tests.sh [pytest arguments]`; it uses the
  shared environment from `scripts/dev-env.sh` and puts this checkout's `src/` on
  `PYTHONPATH`. Do not create virtualenvs, install packages, or `source`
  `scripts/dev-env.sh` (it ends with `exit`).
- Keep command output bounded: `scripts/run-quiet.sh` prints one line and a log path.
- The `milburn` package has no runtime dependencies:
  `PYTHONPATH=src python3 -m milburn.app.cli ...` runs the CLI.
- Live harness runs need an explicit sandbox: Codex defaults here are full access.

## Context discipline for the builder

- Spawn reviewers fresh, with a brief; never fork the transcript.
- Before stopping or when context is above about half, write the next action, open
  PRs, and blockers in the issue you are working on.

## Safety boundaries

- Preserve user changes and unrelated work. Do not reset or destructively clean a
  checkout.
- Do not expose secrets in prompts, commits, logs, issues, or fixtures.
- Do not change any configured Git identity.
- Worktrees provide change isolation, not a security sandbox.
