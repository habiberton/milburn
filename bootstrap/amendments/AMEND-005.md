# AMEND-005 — Remove independent review from the plan-amendment gate

## Authority

- Source: direct user instruction in a Claude Code session on 2026-11-04, after the coordinator spawned Specification and Standards reviewers for AMEND-004: "we shouldn't need a full review cycle of the amendments".
- Authorized task: remove the independent-review requirement for amendment records; no other gate step changes.

## Requested change

Remove "independent review" from the conditions for resuming dispatch after an
amendment. An amendment record and its specification edits are not reviewed by
Specification or Standards reviewers; the user's authorization and the PR merge
are the approval. The remaining gate steps are unchanged: a remotely merged PR,
remote read-back, primary-checkout reconciliation, and a clean
`bootstrap/amendments/validate.py --preflight`. Review of task candidates under
the risk-based review procedure is not changed.

## Affected tasks

- No task's scope, dependencies, or acceptance criteria change.
- Any amendment pending or created after this one is affected prospectively.
- AMEND-004: its pending independent review is no longer required.

## Active-work impact

| Work | Classification | Review decision |
|---|---|---|
| AMEND-004 independent reviews (`amend004_spec_review`, `amend004_standards_review`) | needs_steering | Stop these reviewers and proceed with AMEND-004's PR, merge, read-back, and reconciliation. |
| MB-009/a01 correction | unaffected | Continue on the same branch, worktree, ownership, and generation. |
| MB-025/a01 | unaffected | Continue on the same branch, worktree, ownership, and generation. |
| MB-023/a01 | unaffected | Governed by AMEND-004; no change from this amendment. |

## Registry and specification changes

- Registry changes: none.
- Specification changes: `AGENTS.md` Plan-amendment gate and `bootstrap/README.md` Plan-amendment gate drop the independent-review step and state that amendments get no Specification or Standards review. PRD and ARCH unchanged.
- GitHub changes: none.

## Effectiveness

- Planning commit: pending
- Effective remote PR: pending
- Effective merge commit: pending
- Dispatch status: frozen
- Resolution status: pending

No independent review was run on this amendment, consistent with the change it
makes; the user authorized it directly.
