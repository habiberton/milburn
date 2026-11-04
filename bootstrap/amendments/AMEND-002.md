# AMEND-002 — Risk-based independent review

## Authority

- Source: direct user instruction in the root coordinator session.
- Requested on: 2026-11-03 America/Los_Angeles.

## Requested change

Replace the blanket two-pass independent-review default with recorded,
risk-based selection between Specification-plus-Standards review and one
Focused review. Preserve coordinator verification, acceptance and path checks,
required tests, smoke tests, and PR evidence for every candidate.

## Affected tasks and active-work impact

| Work | Classification | Review decision |
|---|---|---|
| MB-005 | completed history | No rewrite; its two-pass evidence remains. |
| MB-006/a01 | unaffected | Continue with both Specification and Standards because it is a Codex adapter with prior blocking findings. |
| MB-020/a01 | needs integration steering | Preserve candidate; select both passes because it changes shared agent policy and its scope now overlaps this amendment. |
| MB-022 and future high-risk tasks | unaffected before launch | Apply the two-pass risk criteria. |
| Future low-risk tasks | unaffected before launch | Permit one Focused pass only when all low-risk conditions hold. |

No active implementation attempt changes generation, branch, worktree, or
ownership.

## Policy changes

- `AGENTS.md`: root integration selects and records review mode; the review
  section defines the two-pass and Focused risk classes and escalation rule.
- `bootstrap/README.md`: PR evidence includes the selected mode/reason and the
  same prospective risk gate.
- Task progress and PR bodies record the selected mode and reason.
- A blocking Focused finding requires both fresh Specification and Standards
  reviews of the corrected candidate.
- Scope expansion, amendment changes to authority/dependencies, or uncertainty
  selects the two-pass mode.
- GitHub task/dependency changes: none; this amendment changes coordinator
  review policy and PR evidence only.

## Effectiveness

- Planning commit: `0398b0e3d0a11f88b9728ea48a8935b1b2eb1840`
- Effective remote PR: #29 (`https://github.com/habiberton/milburn/pull/29`)
- Effective merge commit: pending
- Resolution status: committed; pending MB-006 PR merge and reconciliation

This policy applies prospectively. Completed task history remains unchanged.
