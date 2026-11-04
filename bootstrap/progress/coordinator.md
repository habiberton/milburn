# Bootstrap coordinator progress

## Current wave

Wave 2 — Independent boundaries; reconciling newly ready tasks

## Repository state

- Integration branch: `main`
- Bootstrap baseline: `3d363238b2b1654860beca31c64ba185d37e2928`
- Active workers: none
- Pending candidates: none

## Completed

- Bootstrap specifications and process files were seeded.
- Work waves and task dependencies were recorded.
- GitHub MCP authentication was verified as `habiberton` with private-repository
  access.
- Existing GitHub issues were checked before creation; the repository had none.
- Required Milburn labels were created and verified:
  `milburn:task`, `milburn:ready`, `milburn:in-progress`,
  `milburn:blocked`, `milburn:qa`, `milburn:changes-requested`,
  `milburn:done`, and `milburn:decision-needed`.
- Tasks `MB-001` through `MB-016` were created as GitHub Task issues #1 through
  #16 with stable task markers, exact acceptance criteria, dependency links,
  owned paths, required tests, and initially unassigned owners.
- `bootstrap/tasks.json` now records the GitHub issue mapping and last observed
  remote assignment/status while retaining the local dependency and recovery
  mirror.
- On 2026-11-03 the root coordinator read the approved specifications and all
  bootstrap records, confirmed a clean `main` checkout at the baseline above,
  and found no worker branches, worker worktrees, task progress records, or
  pending candidates.
- The one-time `scripts/bootstrap-repo.sh` setup completed and configured the
  primary checkout as `Milburn Coordinator [BOOTSTRAP/root]`.
- Local reconciliation confirms `MB-001` is the only dependency-ready Wave 1
  task. Wave 1 remains sequential and no implementation worker was launched.
- GitHub CLI authentication was restored and issue #1 was reconciled against
  `MB-001`: the marker, title, acceptance criteria, owned paths, dependencies,
  and required tests match the local registry.
- Issue #1 is open, assigned to `habiberton`, and moved from `milburn:ready` to
  `milburn:in-progress` for builder attempt `a01`.
- The `MB-001` worker branch and worktree were created from exact base
  `a8220daf6cdee16414210b4653f8f1fffdfc6216`, and the worktree identity is
  `Milburn Builder [MB-001/a01]`.
- Builder `/root/mb001_builder_a01` was launched with the bounded `MB-001`
  brief, owned paths, acceptance criteria, required tests, and candidate commit
  protocol. No other implementation worker is active.
- The first candidate required a narrow correction for range-based whitespace
  errors and a stale handoff record. The same worker produced corrected
  candidate `79bf6e4153d0fbc99a90dd62fbb651d122114b4d` without amending the original
  attributed commit.
- Candidate attribution verification passed for both builder commits; the diff
  contains only approved task paths and the assigned task progress record.
- Coordinator verification in a fresh temporary virtual environment passed:
  11 app unit tests, the complete smoke test, editable package installation,
  installed `milburn --help`, installed `milburn --version`, and configuration
  import/loading.
- Independent Spec review passed all five acceptance criteria with no missing,
  incorrect, or out-of-scope behavior.
- Independent Standards review found no hard violations and one accepted low
  judgement call: version `0.1.0` is duplicated in `pyproject.toml` and
  `src/milburn/__init__.py`.
- Candidate `79bf6e4153d0fbc99a90dd62fbb651d122114b4d` was integrated with
  non-squash merge `90ad110db3b0b7cc5e491c3946f0cf37af294b5d`. The only merge
  conflict was the task progress record; the resolution retained the completed
  worker evidence and the coordinator's worktree-identity fact.
- The post-integration app unit tests and complete smoke test passed: 11 tests.
- GitHub issue #1 was labeled `milburn:done` and closed as completed. Issue #2
  was reconciled, remains open and unassigned, and was moved from
  `milburn:blocked` to `milburn:ready` after its dependency completed.
- Issue #2 is now assigned to `habiberton` and labeled `milburn:in-progress`
  for builder attempt `MB-002/a01`.
- The `MB-002` worker branch and worktree were created from exact base
  `b50ae6f6caffe4629e095d9dafb52b2651aba34c` and configured with identity
  `Milburn Builder [MB-002/a01]`.
- Builder `/root/mb002_builder_a01` was launched with the bounded domain task,
  exact owned paths, acceptance criteria, required tests, and candidate commit
  protocol. No other implementation worker is active.
- Root-only push rules were added to `AGENTS.md` and `bootstrap/README.md` in
  commit `608ece7e9dc77f2fd93099e3084f762c088c26b2`: workers and reviewers never
  push, and the root must verify `origin/main` contains the completion commit
  before applying `milburn:done` or closing an issue.
- The `MB-002` worker was interrupted before implementation changes and its
  branch, worktree, base, assignment, and progress record were preserved.
- A root push of local `main` was attempted after the rule change and rejected
  by GitHub repository rule `GH013`: changes to `main` must use a pull request.
- Remote read-back after the rejected push resolved `origin/main` to
  `3d363238b2b1654860beca31c64ba185d37e2928`. It does not contain the
  `MB-001` integration commit `90ad110db3b0b7cc5e491c3946f0cf37af294b5d`
  or completion record `f40d114ce46cab9b7b35e67a5c3b35c8e08e05f6`.
- To enforce the new gate, GitHub issue #1 was reopened and changed from
  `milburn:done` to `milburn:qa`; issue #2 was changed from
  `milburn:in-progress` to `milburn:blocked` without deleting its worktree.
- The one-ticket coordinator PR strategy was committed as
  `9be13421143e146a721e692a3c2e2680c0c59335`. `MB-001` owns integration branch
  `bootstrap/coordinator/MB-001/a01-integration`; it will have exactly one PR.
- The root pushed that branch at `37022feeb2a917bbe6265c4e60ee3c59e37da454`
  and opened evidence-bearing PR #18:
  `https://github.com/habiberton/milburn/pull/18`. GitHub reports it clean and
  mergeable, and `Closes #1` resolves to the intended task issue.
- PR #18 was updated through the same coordinator branch to tip
  `30677950ff1d14a554add1ce21f979d37e977760` and merged using GitHub's merge
  commit method. The remote merge commit is
  `be8f277ffd60b66181afd7fb97e5975179bdfdd8` with two parents.
- The root fetched `origin/main`, verified it equals that merge commit and
  contains both the worker integration history and the prior completion record,
  then fast-forwarded the primary checkout to the same SHA.
- Post-fast-forward verification passed again: 11 app unit tests and the full
  smoke test.
- Closed issue #1 now carries `milburn:done`; open issue #2 retains its existing
  `habiberton` assignment and is restored to `milburn:in-progress`.
- The clean preserved `MB-002/a01` worker branch was fast-forwarded to verified
  baseline `b2df26c73f0cd9c39cd19ec07b5b5d2c24fa872e`, which includes the merged
  `MB-001` history and the durable coordinator PR strategy.
- The same `/root/mb002_builder_a01` worker was resumed with that exact base and
  explicit instructions to return local commits only under the new PR rules.
- Initial `MB-002` candidate `b4fa8c56801f395e53824b888a78c4ccf42ae62b`
  passed attribution, owned-path, whitespace, 52 domain-test, and 63-test smoke
  verification, but independent review rejected it before integration.
- Spec findings: unapproved feature/issue transition edges and public transition
  guards accepting raw strings. Standards findings: missing negative command
  validation tests and duplicated timezone-aware datetime validation.
- The same worker corrected those findings locally without remote mutations.
- Corrected candidate `b661baea1cb70d6eb56e35b5d303ca9aad249579`
  resolved every blocking finding. Coordinator checks passed: three attributed
  commits, approved paths only, exact-range whitespace check, 64 domain tests,
  and 75 total smoke tests.
- Fresh Spec re-review passed all four acceptance criteria. Fresh Standards
  re-review passed with one accepted low judgement call: `CommandArgument` and
  `EventFact` retain similar validation while remaining distinct public domain
  types.
- `MB-002` owns coordinator integration branch
  `bootstrap/coordinator/MB-002/a01-integration` and will have exactly one PR.
- Corrected candidate was non-squash merged on that coordinator branch as
  `fd5cc0554aeef620927ddf444dc344e55a5d74cd`; the only conflict was the task
  progress record, resolved by retaining worker evidence and coordinator
  recovery facts.
- Integrated-branch verification passed: 64 domain tests, 75 total smoke tests,
  and `git diff --check` against `origin/main`.
- The root pushed coordinator branch
  `bootstrap/coordinator/MB-002/a01-integration` at
  `6b9976c234c426163d97287067e2aa082a58a2b4` and opened the single
  evidence-bearing PR #19: `https://github.com/habiberton/milburn/pull/19`.
  GitHub resolves `Closes #2` to the intended issue and reports the PR clean and
  mergeable.
- The same branch was updated to PR tip
  `b752a39058dcc2f046336c1329664f9a126a4f59`; PR #19 merged using GitHub's
  merge-commit method as `a797fb5577b024c95f3648ae6b5189a0d577680c`.
- The root fetched `origin/main`, verified that two-parent merge commit contains
  candidate `b661baea1cb70d6eb56e35b5d303ca9aad249579` and local integration
  `fd5cc0554aeef620927ddf444dc344e55a5d74cd`, then fast-forwarded the primary
  checkout to the exact remote SHA.
- Post-fast-forward verification passed again: 64 domain tests and 75 total
  smoke tests.
- Closed issue #2 now carries `milburn:done`. Issue #3 was reconciled against
  `MB-003`, remains open and unassigned, and moved from `milburn:blocked` to
  `milburn:ready` after its dependency completed.
- Issue #3 is now assigned to `habiberton` and labeled `milburn:in-progress`
  for builder attempt `MB-003/a01`.
- The `MB-003` worker branch and worktree were created from exact base
  `f6084ba1a485d120c72d44f215f66ca499d677c2` and configured with identity
  `Milburn Builder [MB-003/a01]`.
- Builder `/root/mb003_builder_a01` was launched with the bounded persistence
  task, owned paths, required tests, and local-commit-only PR rules.
- Initial candidate `5d7badbd888e7bc32af1e72b5b3066434cd97bd0`
  passed attribution, scope, 24 persistence tests, and 99 total smoke tests, but
  both independent review axes rejected it before integration.
- Reviews reproduced two blocking defects: unknown future migrations were
  accepted while `user_version` was lowered, and unconditional rollback could
  mask a lock failure when transaction entry failed. The same worker corrected
  both locally without remote mutations.
- Corrected candidate `d2498e97feb273bec083e1e287094a0eb20b0791`
  resolved both defects. Coordinator verification passed: four attributed
  commits, approved paths, 31 persistence tests, and 106 total smoke tests.
- Fresh Spec and Standards re-reviews both passed with no actionable findings.
- `MB-003` owns coordinator integration branch
  `bootstrap/coordinator/MB-003/a01-integration` and will have one PR.
- Corrected candidate was non-squash merged as
  `1f1e7f1270ee34cdf753b741230b5ca498e051f2`; the only conflict was the task
  progress record and the resolution retained all worker evidence.
- Integrated-branch verification passed: 31 persistence tests, 106 total smoke
  tests, and `git diff --check` against `origin/main`.
- The root pushed the coordinator branch at
  `9530d4bd09542a4e341dccdd98a37db5fa43b388` and opened evidence-bearing PR
  #20: `https://github.com/habiberton/milburn/pull/20`. GitHub resolves
  `Closes #3` correctly and reports the PR clean and mergeable.
- The same branch was updated to PR tip
  `ff16f3ecc5e9310dd85f6c8882d5d5c455abd204`; PR #20 merged using a two-parent
  merge commit `74bf04d75f73750d878c83bd0af26467d3c14454`.
- The root fetched and verified `origin/main` contains corrected candidate
  `d2498e97feb273bec083e1e287094a0eb20b0791`, fast-forwarded the primary
  checkout to the exact remote merge SHA, and reran 31 persistence/106 total
  smoke tests successfully.
- Closed issue #3 now carries `milburn:done`. Issue #4 was reconciled against
  `MB-004`, remains open and unassigned, and moved from `milburn:blocked` to
  `milburn:ready`.
- Issue #4 is now assigned to `habiberton` and labeled `milburn:in-progress`
  for builder attempt `MB-004/a01`.
- The `MB-004` worker branch and worktree were created from exact base
  `86c11c23f603bc2a8f5b5463d5f8c1807f0644ad` and configured with identity
  `Milburn Builder [MB-004/a01]`.
- Builder `/root/mb004_builder_a01` was launched with bounded workflow paths,
  acceptance criteria, required tests, and local-commit-only PR rules.
- Mandatory continuation preflight was added to `AGENTS.md`,
  `bootstrap/ROOT_PROMPT.md`, and `bootstrap/README.md` in coordinator commit
  `88ad88778bf1e823fa2d56acf5522654a748e568`. It will be included in the single
  `MB-004` coordinator PR; the active worker's owned paths are unchanged.
- User-authorized issue #21 was mirrored as `MB-017`, a Wave 2 task blocked on
  `MB-002`, `MB-003`, and `MB-006`. Its exact owned paths, acceptance criteria,
  and required tests are recorded in `bootstrap/tasks.json`; it must not run
  concurrently with unfinished `MB-006` work.
- `MB-017` is now a dependency of `MB-010`, `MB-011`, and `MB-013`. `PRD.md`
  and `ARCH.md` narrowly admit observability-only Codex-reported token usage
  while retaining the v1 exclusions for pricing, budgets, cost ceilings,
  reservations, and spend-based routing.
- The usage contract requires partial-versus-final observations, explicit
  unavailable usage, deterministic idempotent replay into per-attempt, task,
  role, and workflow totals, no fabricated counts, and no transcript storage.
  Issue #21 remains open with `milburn:blocked` until `MB-006` completes.
- Builder `/root/mb004_builder_a01` returned candidate
  `03d253e23a161dad156fc76ab461e45c8e466e50` (implementation commit
  `52997e58abaff37ac2f64833db751ffd2512b4aa`) with reported evidence of 63
  orchestration tests and 169 total smoke tests. The handoff message contained
  a one-character SHA transcription error; the exact branch tip above was
  resolved from the assigned worktree. Coordinator attribution, approved-path
  scope, 63 orchestration tests, and 169 total candidate smoke tests passed;
  independent review then rejected the candidate before integration.
- Spec review found that `Controller.handle()` accepts an arbitrary event type,
  allowing an otherwise authorized command to append an observational or
  completion event before evidence. Standards review also found that its
  `TypeVar` does not survive through the non-generic command receipt. The same
  worker is correcting the authority mapping, regression coverage, and result
  typing locally; no MB-004 coordinator branch or PR exists yet.
- Corrected MB-004 candidate
  `d69b8627d780d03d0c421e19dbd1bfa743074b00` contains five verified attributed
  commits from the assigned base. Coordinator verification passed 71
  orchestration tests and 177 total candidate smoke tests. Fresh Spec review
  passed all five criteria; final Standards review passed after the worker
  corrected its durable authority-fix SHA to
  `cf80598106ed7f00904e8b19169d761d23b8ccef`.
- User-authorized issues #22 and #23 were mirrored as `MB-018` and `MB-019`
  with their exact blocked GitHub mappings, owned paths, acceptance criteria,
  tests, and progress paths. Both remain open with `milburn:blocked`.
- `MB-018` follows `MB-006` and `MB-017` in Wave 2 and cannot overlap
  unfinished work on either. It now gates `MB-010`, `MB-011`, and `MB-013`.
  `MB-019` precedes and gates `MB-015` in Wave 4; `MB-016` remains transitively
  gated through `MB-015`.
- `PRD.md` and `ARCH.md` now distinguish logical attempts from replaceable,
  generation-fenced Codex sessions and specify validated transcript-free
  handoff manifests, role-specific continuation boundaries, mandatory
  uncertain-effect reconciliation, and the rule that one compaction alone is
  not a replacement trigger. Usage remains observability-only without pricing
  or budget enforcement.
- Accepted MB-004 candidate
  `d69b8627d780d03d0c421e19dbd1bfa743074b00` was non-squash merged on the
  coordinator branch as two-parent integration commit
  `bd0e306c7b4d47ce817da7744d9bab1bc895011b`. The progress-record conflict was
  resolved by retaining worker evidence and coordinator assignment facts.
- Integrated-branch verification passed: 71 orchestration tests, 177 total
  smoke tests, 19 valid task records, and `git diff --check` against
  `origin/main`.
- The root pushed coordinator branch
  `bootstrap/coordinator/MB-004/a01-integration` at
  `defba5782747c7b7e4f81700e9bdec090d368510` and opened the single
  evidence-bearing PR #26: `https://github.com/habiberton/milburn/pull/26`.
  GitHub resolves `Closes #4` to the intended issue and reports the PR clean
  and mergeable.
- PR #26 merged using GitHub's two-parent merge-commit method as
  `0994a9ac5918ccc54ca3d91c39976e294d83506d`. The root fetched and verified
  `origin/main` contains candidate
  `d69b8627d780d03d0c421e19dbd1bfa743074b00`, integration commit
  `bd0e306c7b4d47ce817da7744d9bab1bc895011b`, and PR tip
  `64522a0a86dd79062e4ad3c826e19b7a87259eb1`, then fast-forwarded the primary
  checkout to the exact merge SHA.
- Post-fast-forward verification passed again: 71 orchestration tests, 177
  total smoke tests, and 19 valid task records.
- Closed issue #4 now carries `milburn:done`. Issues #5 through #9 were
  reconciled from `milburn:blocked` to `milburn:ready` after MB-004 completed;
  MB-017, MB-018, and MB-019 correctly remain blocked by unfinished
  dependencies.
- The Wave 2 parallelization gate passed for MB-005 and MB-006: both depend
  only on completed MB-004, their runtime and adapter path sets do not overlap,
  neither requires the other's unfinished implementation, and each has
  independent acceptance tests. The coordinator is beginning with two workers.
- Issues #5 and #6 are assigned to `habiberton` and labeled
  `milburn:in-progress`. Builder assignments `MB-005/a01` and `MB-006/a01`
  are prepared; their progress records will be included in the exact branch
  base checkpoint before worktrees are created.

## Verification

- `scripts/bootstrap-repo.sh`: passed on 2026-11-03; validated 16 tasks across
  6 waves and reran the bootstrap smoke checks.
- `scripts/smoke-test.sh`: passed on 2026-11-03; validated 16 task records and
  the candidate-attribution verifier. The product test suite does not exist yet.
- GitHub read-back verified all 16 issues are open, correctly titled, marked,
  labeled, unassigned, and contain their dependency links and acceptance
  criteria.
- No implementation agents have been launched.

## Blockers

None recorded. The user authorized the protected-branch PR workflow.

## Resume here

Commit the Wave 2 assignment checkpoint, create and configure MB-005/a01 and
MB-006/a01 worktrees from that exact base, record the resolved bases, then
dispatch both bounded workers.
