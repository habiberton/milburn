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
| MB-007, MB-008, MB-009 | must pause before launch | Remain blocked; no worker exists. |
| MB-017, MB-018 | must pause before launch | Remain blocked; no worker exists. |

No active attempt changes generation, ownership, branch, or worktree because of
this amendment.

## Registry and specification changes

- `bootstrap/tasks.json`: mirror MB-022 and add it to the five affected task
  dependency lists.
- `bootstrap/README.md`: document the amendment gate, the active-work exception,
  and dispatch-resumption criteria.
- `PRD.md`: add the user-authorized amendment lifecycle and acceptance behavior.
- `ARCH.md`: add versioned amendment contracts, expected-version application,
  replay, reconciliation, operator evidence, and launch fencing.
- GitHub: retain issue #27 as blocked on MB-020 and add dependency notices to
  issues #7, #8, #9, #21, and #22.

## Effectiveness

- Planning commit: `4c6f773a1612fc431c26919b0c28e8272fb7f78e`
- Effective remote PR: #28 (`https://github.com/habiberton/milburn/pull/28`)
- Effective merge commit: `182b414ad33540730dec5896a64e3e60024cf78c`
- Dispatch status: frozen for new implementation workers
- Resolution status: effective and reconciled; implementation dispatch remains
  frozen until MB-020 and MB-022 are complete

The coordinator may continue already active unaffected work. It may not launch
another implementation worker until this record names the effective commit and
merged PR, the primary checkout contains that merge, and MB-020 plus MB-022 are
complete as required by the amended graph.
