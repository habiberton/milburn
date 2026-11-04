# Bootstrap defect feedback briefs

This directory is the temporary, concise defect record for bootstrap tasks.
It captures checkable lessons from meaningful defects without becoming agent
memory. The durable product feedback service described in `PRD.md` and
`ARCH.md` replaces this workflow after self-hosting.

## Ownership and lifecycle

Workers propose findings under `## Feedback proposals` in their task progress
record. The root coordinator alone creates or changes a task brief, finalizes a
proposal after verification, and supplies the brief link and a feedback summary
under `## Feedback summary` in the task pull request. Minor formatting-only
corrections may be omitted.

Before marking a task done, the coordinator runs
`python3 bootstrap/feedback/validate.py`. Every unresolved or separately scoped
finding must have a linked GitHub issue. Every resolved finding must identify
its fix commit and regression command plus result evidence.

Keep exactly one brief per task at `bootstrap/feedback/<task-id>.md`. Create the
brief when the task has a meaningful finding or reaches coordinator
finalization; use `- None recorded.` when no qualifying finding exists. Retain
briefs with the bootstrap archive after self-hosting so issue and pull-request
history keeps stable links. Do not copy prompts, transcripts, chain-of-thought,
private reasoning, secrets, terminal captures, or large command logs into a
brief.

## Exact brief format

Use this complete shape. Field names and order are validated. Each value stays
on one line; use a short context pointer instead of copied logs. When historical
evidence was not recorded, write `unavailable — <reason>` rather than inferring
it.

```markdown
# MB-123 feedback brief

## Findings

### MB-123-F001

- Discovery phase: review
- Severity: meaningful
- Symptom: Concise observed behavior and a pointer to its evidence.
- Root cause: Concise verified cause, or unavailable — not recorded.
- Resolution: Concise change made, or unavailable — unresolved.
- Fix commit: 0123456789abcdef
- Regression evidence: `python3 -m pytest tests/example -q` — 3 passed.
- Lesson: Concise reusable lesson.
- Status: resolved
- Attempt: a01
- Worker candidate: fedcba9876543210
- Coordinator integration: 1234567890abcdef
- GitHub PR: #123
- Linked issue: unavailable — resolved within originating task.
```

Allowed discovery phases are `review`, `test`, `integration`, `recovery`, and
`production`. Severity is `blocking` or `meaningful`. Status is `resolved`,
`unresolved`, or `separately-scoped`.

Feedback IDs use `<task-id>-F<three digits>`, start at `F001`, never change, and
are unique across this directory. The ID task prefix and heading must match the
file name, and the task ID must exist in `bootstrap/tasks.json`. Attempts use
`a<two digits>`. Commit pointers use 7–40 hexadecimal characters. GitHub pull
requests and linked issues use `#<number>` or a GitHub URL; use an explicit
`unavailable — <reason>` only where the format permits missing context.

## Proposal format

Workers copy only the finding block beginning with `### <feedback-id>` into
their `## Feedback proposals` progress section. A worker may propose an ID, but
the coordinator resolves collisions and owns the finalized ID. Each proposal
ends with checkable completion criteria: the evidence the coordinator must
verify, whether a fix and regression result are required, and which linked
issue is required for unresolved or separate scope.
