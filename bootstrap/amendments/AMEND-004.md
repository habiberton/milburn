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

- Registry changes: mark MB-023 blocked while this amendment is pending; add an MB-023-only review exception and known-limitations record; retain its exact candidate SHA and dependencies; finalize `bootstrap/feedback/MB-023.md` with MB-023-F001/F002 as unresolved and linked to follow-up issues #49/#50.
- Specification changes: none to PRD.md or ARCH.md; the effective amendment record is the narrow task-specific authority that supersedes only MB-023's automatic post-Focused escalation. AGENTS.md, bootstrap/README.md, and bootstrap/ROOT_PROMPT.md remain otherwise unchanged.
- GitHub changes: issue #41 moves to `milburn:decision-needed` while pending, then returns to `milburn:qa` only after the effective amendment is remotely reconciled and the preserved candidate is integrated and tested. Follow-up issue #49 tracks MB-023-F001 and #50 tracks MB-023-F002 after #41 closes; neither issue claims a fix.

## Effectiveness

- Planning commit: `d2c0d4aede7435116e09b4ca96ba3ccbadd3bf05`
- Effective remote PR: #52 (https://github.com/habiberton/milburn/pull/52)
- Effective merge commit: `df266743c23644d0e9ae064e624cc228b13b9009`
- Dispatch status: resumed
- Resolution status: effective and reconciled

PR #52 merged through GitHub's merge-commit method with parents
`62ef4b404e5affeb97bfb09e33c5f17795606db2` and the final independently
reviewed planning tip. The coordinator fetched `origin/main`, proved it
contains both the planning tip and merge commit, verified the two-parent
topology, and fast-forwarded the primary checkout. Follow-up issues #49/#50
remain open, issue #41 returned to `milburn:in-progress`, and the exact
preserved candidate remains unchanged. This reconciliation resumes dispatch;
the exception applies only to MB-023 and does not claim either finding is fixed.
