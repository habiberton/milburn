# AMEND-004 — Accept MB-023 known CLI limitations without escalated review

## Authority

- Source: direct user instruction on 2026-11-04: "skip the MB-023 standards and specification review as long as the scripts are functional we can keep the bug for now".
- Authorized task: create and apply a narrow MB-023-only exception that preserves candidate `915e9e98e666339b6075eb0d016c1ea6ab31c339`, accepts the two Focused-review findings as known deferred limitations, and waives the otherwise mandatory fresh Specification and Standards escalation. No other task or review policy is changed.

## Requested change

Accept MB-023 candidate `915e9e98e666339b6075eb0d016c1ea6ab31c339`
without correcting MB-023-F001/F002 and without the fresh Specification and
Standards passes normally required after a blocking Focused review. Functional
evidence remains mandatory: candidate attribution, owned-path/diff checks, the
16-test public CLI suite, and the full smoke suite must pass on the exact
candidate. The accepted known limitations are:

- Shell keywords and shell-only builtins may pass the current discovery check
  and behave inconsistently between quiet and verbose execution.
- Control characters in a configured log-directory path may make the displayed
  summary span more than one physical line.

The limitations are recorded, not represented as fixed. MB-023 still follows
the normal coordinator integration, PR, remote read-back, and post-merge test
gates. This exception does not waive candidate verification, feedback
recording, integration review of unrelated changes, or any rule for another
task.

## Affected tasks

- MB-023: preserve candidate `915e9e98e666339b6075eb0d016c1ea6ab31c339`,
  record the known limitations, accept its existing Focused review as the final
  independent pass despite its blocking verdict, and do not run the resumed
  correction worker or fresh Specification/Standards escalation.
- MB-009, MB-024 through MB-029, and all product tasks: no scope, dependency,
  acceptance, or review change.

## Active-work impact

| Work | Classification | Review decision |
|---|---|---|
| MB-009/a01 authorized correction | unaffected | Continue on the same branch, worktree, ownership, and generation. |
| MB-023/a01 resumed correction | must_stop | Interrupted before changes; preserve exact candidate `915e9e9` and do not resume the correction. |

## Registry and specification changes

- Registry changes: mark MB-023 blocked while this amendment is pending; add an MB-023-only review exception and known-limitations record; retain its exact candidate SHA and dependencies.
- Specification changes: none to PRD.md or ARCH.md; the effective amendment record is the narrow task-specific authority that supersedes only MB-023's automatic post-Focused escalation. AGENTS.md, bootstrap/README.md, and bootstrap/ROOT_PROMPT.md remain otherwise unchanged.
- GitHub changes: issue #41 moves to `milburn:decision-needed` while pending, then returns to `milburn:qa` only after the effective amendment is remotely reconciled and the preserved candidate is integrated and tested.

## Effectiveness

- Planning commit: pending
- Effective remote PR: pending
- Effective merge commit: pending
- Dispatch status: frozen
- Resolution status: pending
