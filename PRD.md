# Milburn Product Requirements Document

**Status:** Approved by the user, 2026-11-04, with the recommendations in §14.
Replaces the v1 `PRD.md` and the v2 draft additions.

**Sources:** the user's direction decisions in
`bootstrap/reviews/REVIEW-2026-11-04.md` ("the review"). Older text is
cited as `PRDv1 §n` (`PRD.md` at `6db08eb`), `PRDv2 V2-n` and `ARCHv2 D2-n` (branch
`design/v2-draft` at `d67063a`). Read a cited section with
`git show <ref>:<file>`. The cited text applies only where this document says so.

**IDs:** requirements are `R<n>`; `ARCH.md` decisions are `A<n>`; integration gaps
from the MB-030 live run are `G<n>`. `ARCH.md` §12 resolves every gap.

## 1. Product

Milburn is an **agent distro**: a way to build software by talking to one agent
that runs a team of agents.

- The **user** talks to one **Coordinator**. The Coordinator runs inside the user's
  own Claude Code or Codex session.
- The Coordinator turns requests into **tasks** and dispatches **role agents**
  (Coder, Tester, Architect, Designer) to work on them in parallel, each in its own
  Git worktree.
- The Coordinator holds judgment. The **`milburn` CLI** holds enforcement: what a
  script can check, the independent QA gate, journaled external effects, merge
  authority, and the event record.
- Finished work leaves the workshop according to the project's **delivery mode**.

What makes Milburn different, and must survive every later change:

1. Token and session telemetry on one event store.
2. Specs in OpenSpec format, written only when asked for.
3. Independent QA with no self-approval.
4. Journaled external effects.
5. Built-in processes.

## 2. Terms

| Term | Meaning |
|---|---|
| User | The person who talks to the Coordinator and owns every decision. |
| Coordinator | The one agent the user talks to. Plans, asks, dispatches, and reports. Holds no authority the CLI does not grant. |
| Role agent | An agent launched for one task attempt in one role: Coder, Tester, Architect, or Designer. More roles are data (R12). |
| Harness | The agent runtime: Claude Code or Codex. |
| Request | What the user asks for, in free form or by choosing a built-in process. |
| Work item | The unit of delivery. Owns one integration branch and the tasks that build it. |
| Task | One piece of work with one type, one acceptance contract, and one owner at a time. |
| Task type | Configurable data naming a task's role, result schema, and rules (R12). |
| Attempt | One try at one task by one role agent. Has one worktree lease and one or more session generations. |
| Built-in process | A named stage table the user can choose instead of a free-form request (R20). |
| Stage | One row of a built-in process: who acts, what it produces, its gate, and how it may be skipped. |
| Gate | A check the CLI runs mechanically before a stage or task can finish. |
| Delivery mode | Per project: `local-only`, `pr`, or `auto-merge` (R7). |
| Mechanical | Checkable by a script without reading words (R9). |

## 3. Scope of this release

In scope:

- Claude Code and Codex, for the Coordinator and for every role agent.
- One local machine, one user, any number of repositories.
- GitHub as the remote and issue tracker when delivery mode is `pr` or `auto-merge`.
- Free-form requests, and three built-in processes: Start from scratch, Add a
  feature, Fix a bug.

Out of scope until §15 ("Later") items are approved: remote or phone access,
research tools, harnesses other than Claude Code and Codex, pricing and budgets,
Agent2Agent, task trackers other than GitHub, and creating repositories.

## 4. The Coordinator

- **R1. One conversation.** The user talks only to the Coordinator. Role agents never
  talk to the user directly; their questions reach the user through the Coordinator.
- **R2. Runs in the user's harness.** The Coordinator is Claude Code or Codex, started
  by the user, with Milburn's Coordinator skill and instructions installed by
  `milburn init`. Milburn does not host or keep alive the Coordinator process.
- **R3. Judgment, not authority.** The Coordinator decides what to ask, how to split
  work, which process to offer, and how to read results. It changes durable state
  only by calling the CLI. It never merges, pushes, or mutates GitHub itself.
- **R4. Offers processes at the start.** When a request arrives, the Coordinator
  handles it free-form by default. It offers a built-in process when one fits, and
  the user chooses. The choice is recorded.
- **R5. Resumes from a digest.** A new or rotated Coordinator session starts from
  `milburn status --digest`, not from history (R32).

## 5. Role agents and harnesses

- **R6. Isolation.** Every role agent runs headless for one attempt, in its own Git
  worktree, under a sandbox the CLI chooses. A role agent never receives full
  machine access, GitHub write authority, or the ability to launch another agent.
- **R7. Delivery modes.** Each project sets one mode in its Milburn configuration:
  - `local-only`: passed work is merged into the work item's local integration
    branch. Nothing is pushed.
  - `pr` (default): the CLI pushes the integration branch and opens one pull request
    per work item. The user merges.
  - `auto-merge`: as `pr`, then the CLI merges the pull request with a merge commit,
    but only after every task in the work item passed independent QA and the
    repository's required checks pass on the pushed head.
- **R8. Harness per role.** Configuration maps each role to a harness, model, and
  effort. The Tester runs on a different harness from the Coder of the task it tests,
  by default. The user can turn that off per project. When the configured harness is
  unavailable, the dispatch fails with a clear reason; it never silently uses another.

## 6. The `milburn` CLI

- **R9. Boundary rule.** The CLI owns a check when a script can decide it without
  reading words: a SHA, a path, an exit code, a schema, a set membership, a count, an
  identity, a digest. The Coordinator owns everything that needs reading or judgment.
  The CLI additionally owns the independent QA gate and completion policy, journaled
  GitHub and pull-request effects, merge authority per delivery mode, and the event
  record, even where they involve policy rather than pure checks.
- **R10. Commands.** The CLI provides worktree leases, dispatch and collection of
  role-agent attempts, gates, the QA gate and task completion, integration and
  delivery, journaled GitHub effects, decision and question recording, bounded
  command execution, and read-only `status`, `reconcile`, `usage`, and `events`
  reports. `ARCH.md` §4 lists them.
- **R11. Who may call what.** The Coordinator calls any command. A role agent may
  call only read-only commands and bounded command execution; its sandbox cannot
  write the event store. Every mutating command records its actor, is idempotent
  under retry, and refuses rather than guesses when its preconditions fail.

## 7. Task types and specs

- **R12. Task types are data.** A task type names its role, result schema, role
  rules, skills, sandbox, and whether its result needs independent QA. Types can be
  added, renamed, or removed in configuration without code changes. Milburn ships
  defaults (`ARCH.md` §6); their names are provisional.
- **R13. Specs only on request.** Milburn writes specs, a PRD, or an ARCH only when
  the user asks for one or chose a built-in process that includes a spec stage.
  A free-form request never produces a spec as a side effect.
- **R14. The spec task type defaults to OpenSpec.** Fold in PRDv2 V2-23, V2-26 to
  V2-31 and ARCHv2 D2-6, §4.9, §4.10, with these settled points:
  - OpenSpec is used as published, pinned by version and digest, and invoked only
    through the CLI. It is never forked, and its telemetry is always off.
  - Milburn's `milburn-spec` schema has no tasks artifact: Milburn tasks are the
    task list.
  - Every requirement has a scenario. Scenario IDs are derived from names, are
    unique, and survive renames through recorded aliases.
  - Build tasks cite the scenario IDs they implement. The Tester maps its evidence
    to those IDs.
  - The change is archived into the living specs as the last commit on the work
    item's integration branch, after every task passed QA. The living specs on the
    default branch change only when that branch merges, so abandoned work never
    changes them.
- **R15. Spec location.** Specs live in the target repository, on the work item's
  integration branch, so every task worktree created from that branch contains
  them (G6).

## 8. Independent QA

- **R16. No self-approval.** A task completes only through `milburn task complete`,
  which requires a passed QA report from a Tester attempt that is not the Coder
  attempt, not the Coordinator, and, by default, not on the Coder's harness. The
  report must name the exact candidate SHA being completed.
- **R17. Testing is evidence.** The Tester tests the exact candidate SHA in a clean
  worktree, records commands, results, and log references, maps evidence to the
  cited scenario IDs, and returns `passed`, `changes_requested`, or
  `decision_needed`. The CLI decides from the report's structure; the Tester's prose
  is never evidence.
- **R18. Bounded rework.** Failed QA returns the task to a Coder as a new attempt.
  The four convergence rules and the user-only acceptance of a known limitation in
  PRDv1 §12.5 apply unchanged.
- **R19. Defect feedback.** Each blocking finding has a stable identity, category,
  location, and evidence reference, and a fix records its regression test. Feedback
  is concise evidence, never transcript. Recurring findings may be cited, briefly,
  in later briefs for the same area (PRDv1 §11.1, condensed).

## 9. Built-in processes

- **R20. Processes are stage tables.** A built-in process is a validated table of
  stages (ARCHv2 D2-1; shape in `ARCH.md` §7). Adding a process is data, not code.
- **R21. Skippable on the record.** Any stage can be skipped. The skip records its
  reason and authority (the user, or a policy named in the table). Skipping QA makes
  the work item ineligible for `auto-merge`; it falls back to `pr`.
- **R22. Grill before design.** Discovery is a conversation between the Coordinator
  and the user, recorded in a question ledger (PRDv2 §4.2: V2-1 to V2-4). The grill
  gate passes only when no blocking question is open, every assumption has a
  recorded user acceptance, every deferral names an owner and follow-up, and the
  ledger digest matches the one the next stage was given.
- **R23. Design stage.** For user-facing work, a Designer produces a few variants per
  screen or flow, the user picks or combines, and the approved result is a
  `DesignSpec` that tasks cite and the Tester checks against (PRDv2 V2-8 to V2-12,
  condensed). Work with nothing user-facing skips design with that reason. Design may
  return questions to the grill.
- **R24. Initial processes.**
  - **Start from scratch:** ask what to build; repository; discovery and grill;
    design; OpenSpec spec; tasks; parallel build; independent QA; delivery.
  - **Add a feature:** discovery and grill; design; spec; tasks; parallel build;
    QA; delivery.
  - **Fix a bug:** reproduce and triage with the user; a regression test written
    first; fix; QA; delivery. The spec stage is skipped by default with reason
    "bug fix with no behavior change"; the user can turn it on.
- **R25. Repository stage.** "Use an empty repository the user provides" works: the
  CLI checks that the path is a Git repository with no commits beyond an optional
  initial one and a clean tree. "Create one" requires a recorded user approval and
  then refuses with "not available yet". Repository creation is undecided (§15).

## 10. Telemetry and observability

- **R26. One spine.** The event store is the only durable source. Status, reports,
  metrics, and any live view are projections of it and rebuild by replay (PRDv2
  V2-33, V2-34).
- **R27. Activity with provenance.** Agent activity events (turns, tool calls,
  usage, compactions, errors) record their source and fidelity. Missing detail is
  recorded as unavailable, never inferred. Terminal text is never evidence (PRDv2
  V2-35, V2-36).
- **R28. Usage per harness.** Each harness adapter maps its native usage fields onto
  one usage vocabulary (`ARCH.md` §9). Usage is recorded per role, task, model,
  attempt, and session generation, with launch context size and compaction count.
- **R29. Metrics from events.** Flow time per stage, attempt duration, rework rounds,
  first-attempt QA pass rate, and tokens by role, model, and attempt, including cache
  ratio, launch size, peak context, and compactions (PRDv2 V2-39). Tokens per
  delivered work item is a first-class report.
- **R30. Assistant prose.** Assistant output may be shown in monitoring when the
  harness exposes it. It is never evidence, never copied into briefs, handoffs, or
  feedback, and never an input to a CLI decision.

## 11. Context and token discipline

These are requirements, learned from building Milburn itself (`ARCH.md` §10 has the
evidence and mechanisms).

- **R31. No inherited transcripts.** Every attempt and every replacement session
  starts from a generated brief, plus a validated handoff manifest when replacing.
  No launch inherits a parent's or predecessor's conversation.
- **R32. The Coordinator never re-reads history.** It resumes from a bounded state
  digest of open decisions, active attempts, ready tasks, and blockers. Mechanical
  multi-step procedures (integration, delivery, reconciliation) are single CLI
  commands, so the Coordinator never re-derives them from documents.
- **R33. Bounded briefs.** A brief holds task identity, acceptance criteria with
  scenario IDs, exact commands, role rules, and pointers with line ranges into specs.
  It embeds a digest of its sources, is rejected when stale, and fails closed over
  its size budget rather than truncating.
- **R34. Rotation at quiescent points.** Sessions are replaced from a validated
  checkpoint when observed context use reaches a threshold: by default 35% of the
  window or 100k tokens, whichever is first, for the Coordinator, and 50% for role
  agents. One compaction alone does not trigger replacement. Unsupported
  observations never trigger it.
- **R35. Bounded command output.** Commands run for agents return a one-line summary,
  the failing excerpt on failure, and a durable log reference. Full output never
  enters agent context by default.
- **R36. Schema-enforced results.** Every role result is validated against a JSON
  schema generated from the domain models and, where the harness supports it,
  enforced at generation time. Only the last final message of a run is the result.
- **R37. Lean launches.** Each launch records its first observed input size. Launches
  run with an isolated, minimal harness configuration where the harness supports it,
  so user plugins and global instructions do not inflate every attempt.
- **R38. Review by risk.** Independent QA is required for every task with a result
  that changes code. Extra review passes are chosen by risk, not applied to every
  task, because each pass costs a full launch.

## 12. Safety

- **R39.** Role agents never receive credentials, full-access sandboxes, or network
  access beyond what their task type declares.
- **R40.** Agents commit under a per-attempt Git identity, never the user's global
  identity (G22).
- **R41.** Every GitHub effect is journaled before it is attempted, carries an
  idempotency key, and is reconciled when its outcome is uncertain.
- **R42.** Worktrees isolate changes; they are not a security sandbox. The boundary
  between the CLI and the Coordinator is a guardrail: the Coordinator runs with the
  user's own permissions, and `milburn init` installs harness rules that route
  merges, pushes, and GitHub mutations through the CLI.

## 13. Acceptance criteria

1. A free-form request in a configured repository dispatches a Coder on Codex and a
   Tester on Claude Code (or the reverse), and the task completes only after the
   Tester's passed report for the exact candidate SHA.
2. `milburn task complete` refuses a QA report from the Coder's own attempt, from the
   Coordinator, from the Coder's harness (unless configured otherwise), or for a
   different SHA.
3. In `pr` mode, a work item with two dependent tasks produces one pushed integration
   branch containing both, and one pull request. The second task's worktree was
   created from an integration head that contained the first.
4. In `auto-merge` mode, the CLI refuses to merge while any task lacks a passed QA
   report or a required check is failing or pending, and merges with a merge commit
   once both hold.
5. In `local-only` mode, no command pushes or calls GitHub.
6. A free-form request produces no spec file.
7. "Add a feature" produces a validated OpenSpec change on the integration branch;
   every build task cites existing scenario IDs; a citation of a missing ID is
   refused; the change is archived only after every task passed QA.
8. Skipping any stage records its reason; skipping QA makes `auto-merge` fall back
   to `pr`.
9. The grill gate refuses with each unmet condition listed.
10. "Create repository" refuses with "not available yet" after a recorded approval,
    and refuses without one.
11. Every role run's result is rejected unless it matches its generated schema, and
    only the final message is parsed.
12. `milburn usage` reports tokens per role, task, model, attempt, and harness, with
    launch size and compactions, and it rebuilds identically after replay.
13. A role agent cannot write the event store, push, or call a mutating CLI command;
    the attempt is recorded as refused.
14. Every module marked retire in `ARCH.md` §11 is unwired and deleted in its own
    task, with the full suite passing after each removal.

## 14. Open items

Items marked **Decided** were settled with the user's approval on 2026-11-04. The
rest need validation before the task that depends on them starts. `ARCH.md` §13 has
the details.

1. **Decided:** GitHub effects use `gh` and REST behind the existing contracts and
   journal.
2. Claude Code headless facts: schema enforcement, sandbox, usage fields, resume.
3. Per-attempt harness configuration isolation for Codex and Claude Code (G18).
4. Harness rules that stop the Coordinator from merging or pushing directly.
5. OpenSpec checks (PRDv2 §12 item 4), with the fallback in the review's finding V-b.
6. **Decided:** the default task types and roles are named as in `ARCH.md` §6; they
   stay renameable data.
7. Grill defaults (questions per turn, rounds before escalation).
8. Design rendering engine (PRDv2 V2-13).
9. **Decided:** the CLI records a user's answer as relayed by the Coordinator, with
   a verbatim quote. It can check that an answer exists, not that the user gave it.
   Accepted as a known limit.

## 15. Later

Not in this release. Each needs its own approved change before work starts.

- Remote and phone access (PRDv2 V2-43 to V2-45; review finding V-d proposes
  read-only monitoring first).
- The research gateway (PRDv2 V2-5 to V2-7).
- Harnesses beyond Claude Code and Codex.
- Pricing, budgets, and cost-based routing.
- Agent2Agent protocol (decided: skip for now).
- Trackers other than GitHub (Linear, Notion).
- Repository creation in "Start from scratch".
- More built-in processes.
