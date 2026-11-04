# AMEND-002 — Risk-based independent review

## Authority

- Source: direct user instruction in the root coordinator session.
- Authorized task: coordinator review-policy amendment carried by MB-006 / PR #29.
- Requested on: 2026-11-03 America/Los_Angeles.

## Requested change

Replace the blanket two-pass independent-review default with recorded,
risk-based selection between Specification-plus-Standards review and one
Focused review. Preserve coordinator verification, acceptance and path checks,
required tests, smoke tests, and PR evidence for every candidate.

## Affected tasks

- MB-005 completed history remains unchanged.
- MB-006 and MB-020 retain Specification and Standards review.
- MB-022 and future tasks select review mode from the recorded risk policy.

## Active-work impact

| Work | Classification | Review decision |
|---|---|---|
| MB-006/a01 | unaffected | Continue with both Specification and Standards because it is a Codex adapter with prior blocking findings. |
| MB-020/a01 | needs_steering | Preserve candidate; select both passes because it changes shared agent policy and its scope now overlaps this amendment. |

No active implementation attempt changes generation, branch, worktree, or
ownership. Completed MB-005 and nonstarted future tasks are affected policy
subjects but are not active-work rows.

## Registry and specification changes

- Registry changes: none.
- Specification changes: `AGENTS.md` and `bootstrap/README.md` record review
  selection, PR evidence, risk classes, and escalation; approved product and
  architecture remain unchanged.
- GitHub changes: none; this amendment changes coordinator review policy and PR
  evidence only.

## Effectiveness

- Planning commit: `0398b0e3d0a11f88b9728ea48a8935b1b2eb1840`
- Effective remote PR: #29
- Effective merge commit: `d276cc255088c9ac91eb04da319719eb66c64abe`
- Dispatch status: unchanged
- Resolution status: effective and reconciled

This policy applies prospectively. Completed task history remains unchanged.
