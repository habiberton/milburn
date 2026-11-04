# AMEND-001 — Durable plan-amendment gate

## Authority

- Source: direct user instruction in the root coordinator session.
- Authorized task: MB-022 / GitHub issue #27.
- Requested on: 2026-11-03 America/Los_Angeles.

## Requested change

Add a durable bootstrap and product plan-amendment gate. A pending amendment or
uncommitted coordinator planning change freezes new worker dispatch, while
already active work receives an explicit impact classification. Complete
MB-020 and MB-022 before dispatching additional Wave 2 workers.

## Affected tasks

- Added: MB-022 in Wave 2, depending on MB-004 and MB-020.
- Newly gated by MB-022: MB-007, MB-008, MB-009, MB-017, and MB-018.
- Sequencing: after safe completion of already active MB-005 and MB-006,
  complete MB-020 and then MB-022 before further implementation dispatch.

## Active-work impact

| Work | Classification | Decision |
|---|---|---|
| MB-005/a01 | unaffected | Continue correction, independent review, and its coordinator PR. |
| MB-006/a01 | unaffected | Continue correction, independent review, and its coordinator PR. |
| MB-020/a01 | unaffected | Continue its already-started feedback-process implementation; integrate after MB-005 and MB-006 reach safe completion. |

No active attempt changes generation, ownership, branch, or worktree because of
this amendment. Nonstarted MB-007, MB-008, MB-009, MB-017, and MB-018 remain
affected tasks but are not active-work rows.

## Registry and specification changes

- Registry changes: `bootstrap/tasks.json` mirrors MB-022 and adds it to the five
  affected task dependency lists.
- Specification changes: `bootstrap/README.md`, `PRD.md`, and `ARCH.md` record
  the gate, lifecycle, expected-version replay, reconciliation, and launch
  fencing.
- GitHub changes: issue #27 remains blocked on MB-020 and dependency notices are
  recorded on issues #7, #8, #9, #21, and #22.

## Effectiveness

- Planning commit: `4c6f773a1612fc431c26919b0c28e8272fb7f78e`
- Effective remote PR: #28
- Effective merge commit: `182b414ad33540730dec5896a64e3e60024cf78c`
- Dispatch status: resumed
- Resolution status: effective and reconciled

AMEND-001 itself became effective and reconciled when PR #28 merged and the
primary checkout read back its merge commit, so its amendment lifecycle no
longer freezes dispatch. MB-007, MB-008, MB-009, MB-017, and MB-018 remained
separately gated by their explicit MB-020 and MB-022 task dependencies. This
record does not claim that MB-022 is remotely merged or complete.
