# Milburn Product Requirements Document

**Status:** Greenfield v1 specification

**Product:** Milburn

**Initial harness:** Codex only

**Purpose:** Define the smallest useful release and its acceptance criteria.

## 1. Product summary

Milburn is a local-first control plane that coordinates specialized Codex agents. A user supplies a software goal. Milburn plans the work, designs the solution, creates GitHub issues, assigns one issue at a time to a Coder, and sends each candidate implementation to an independent Tester.

Milburn does not replace Codex. Codex owns each agent's model-and-tool loop. Milburn owns the workflow around the agents: role assignment, GitHub issue state, tmux processes, isolated workspaces, crash recovery, validation, and delivery.

> Codex agents may propose and perform work. Milburn's controller decides which step may run, records what happened, and decides whether the evidence is sufficient to continue.

## 2. Deliberately narrow first release

Version 1 supports only Codex. It does not choose among Codex, Claude Code, OpenCode, or model providers. It omits pricing and monetary policy, but records observability-only token usage when Codex reports it. This keeps the first engineering problem focused on reliable coordination between a primary controller and worker agents.

The release still proves the important agent-distro behavior:

- Each agent has one bounded role.
- Every agent runs in its own tmux window.
- Work moves through specs, issues, commits, progress records, and results rather than copied transcripts.
- A replacement Coder can recover after a crash.
- The Coder cannot approve its own work.

## 3. Problem

Long software tasks often outlive one agent session. A fresh agent may repeat finished work, miss uncommitted changes, or declare a partially built feature complete. A single agent may also blur planning, implementation, and testing into one unreviewed activity.

Milburn must turn a request into an ordered workflow, separate planning from coding and QA, preserve enough state for safe resumption, isolate changes, and explain every transition.

## 4. Goals

Milburn v1 must:

1. Accept a natural-language request bound to one GitHub repository.
2. Use Codex for all agent roles.
3. Coordinate Coordinator, Planner, Classifier/Router, Architect, Coder, and Tester agents.
4. Start every agent in a dedicated tmux window, including one persistent user-facing Coordinator session.
5. Ask the Planner for a high-level plan.
6. Ask the Architect to create `PRD.md`, `ARCH.md`, and one implementable GitHub issue per task.
7. Use GitHub issues as the durable registry of feature work.
8. Use a controller-owned GitHub MCP connection as the v1 transport for issue mutations and pull-request/check reads.
9. Assign only one issue to each Coder attempt.
10. Give every Coder a dedicated branch and Git worktree.
11. Require Coder startup recovery from the issue, `progress.txt`, Git status, and feature-specific Git history.
12. Require frequent progress updates and coherent commits.
13. Send a Coder's exact commit to a separate Tester.
14. Prevent a Coder from closing or approving its own issue.
15. Record workflow, MCP effects, and process events in a local event store.
16. Recover active work without assuming an unresponsive agent is dead or an interrupted MCP mutation failed.
17. Provide an operator CLI. A dashboard is optional for the first milestone.
18. Ship versioned Codex skills for every agent role and record the exact skill digests used by every attempt.
19. Provide deterministic unit, contract, integration, recovery, skill, and live-evaluation suites with explicit CI gates.
20. Persist Codex-reported token usage as replayable telemetry with per-attempt, task, role, and workflow summaries.
21. Preserve logical agent identity across fenced Codex session generations by using validated durable handoff manifests rather than private transcripts.
22. Persist concise defect observations, resolutions, regression evidence, and recurring lessons without storing private reasoning or unbounded logs.
23. Freeze new agent dispatch while a user-authorized plan amendment is pending, without disrupting active work classified as unaffected.

## 5. Non-goals

Version 1 will not support another harness, select models, attach prices to usage, enforce budgets or cost ceilings, reserve spend, route work based on spend, run a distributed fleet, require a permanent server, automatically merge or deploy, copy private transcripts between roles or replacement sessions, trust Coder test claims as final QA, infer success from process exit, or give agents unrestricted GitHub MCP mutation tools. Token counts and context observations reported by Codex are observability telemetry only and do not require storing prompts or private transcripts. A single compaction is not, by itself, a reason to replace a session. tmux and worktrees are not security sandboxes.

## 6. Agent roster

All roles use Codex. They differ by instructions, permissions, input, and required output.

| Role | Responsibility | Product-code writes | Output |
|---|---|---:|---|
| Coordinator | Maintain the single user-facing conversation, explain fleet activity, present decisions, and relay user answers through the controller. | No | Intake proposals, user decisions, and conversational updates |
| Planner | Turn the request into major stages and identify missing decisions. | No | Plan and decision requests |
| Classifier/Router | Propose which role should handle the next item or event. | No | Next-role proposal and reason |
| Architect | Create `PRD.md` and `ARCH.md`; split the design into GitHub issues. | Docs only | Specs and issue drafts |
| Coder | Implement exactly one ready issue in an isolated worktree. | Yes | Commits, `progress.txt`, implementation result |
| Tester | Test the exact candidate commit against issue acceptance criteria. | No by default | QA report and pass/fail recommendation |

The Coordinator is Milburn's conversational primary agent, but it is not the control plane. It cannot launch agents, mutate GitHub, approve work, or change lifecycle state directly. It asks the deterministic controller to perform allowed operations.

The Classifier/Router proposes the next role. Deterministic controller code checks whether that transition is allowed. The Tester supplies evidence; controller policy decides whether an issue becomes done.

### 6.1 Coordinator session behavior

The operator talks to one persistent Coordinator chat. Each Coordinator turn ends normally; it does not remain loading while workers run. A background watcher queues actionable worker events and wakes the Coordinator only when it must explain a result, request a decision, or report a failure.

If the user interface is closed, events remain durable. When the Coordinator session resumes, it presents unread results and open decisions before accepting unrelated new work.

The logical Coordinator identity survives both fresh model turns and replacement
Codex sessions. Durable decisions, unread notifications, acknowledgements, and
controller state remain authoritative; no replacement depends on replaying the
private transcript.

Worker questions travel through the controller:

```text
Worker DecisionRequest
→ controller validates and records it
→ Coordinator is woken and explains it to the user
→ user answers in the Coordinator chat
→ controller records and validates the answer
→ controller writes the worker inbox message
→ worker acknowledges and resumes
```

### 6.2 Role-specific session lifecycle

- A Coder normally retains one Codex session for one task attempt. One observed
  compaction alone does not trigger replacement; any replacement starts only
  from a validated durable checkpoint.
- Planner and Architect sessions end at their approved plan or architecture
  artifact boundaries.
- Classifier/Router uses short, fresh calls over bounded workflow facts.
- Tester always starts fresh from the exact candidate SHA, acceptance criteria,
  specifications, and clearly labeled Coder claims.

A logical role and attempt can span multiple replaceable session generations
without changing task ownership. Generation fencing prevents late messages or
lifecycle commands from reaching a replacement generation.

## 7. End-to-end workflow

```text
User request in Coordinator chat
    ↓
Coordinator submits a bounded intake proposal to the controller
    ↓
Classifier/Router proposes Planner
    ↓
Planner produces a high-level plan
    ↓
Architect writes PRD.md and ARCH.md
    ↓
Architect drafts one GitHub issue per implementation task
    ↓
Controller creates and orders validated issues
    ↓
Classifier/Router proposes Coder for the next ready issue
    ↓
Coder recovers context, implements, commits, and updates progress.txt
    ↓
Tester validates the exact commit
    ├── fail → evidence is added and the issue returns to a Coder
    ├── design conflict → return to Architect or operator
    └── pass → controller marks the issue done
```

Agents cannot launch peers or close the workflow directly. The Coordinator provides the conversational experience; the controller retains authority.

## 8. GitHub issues as the task registry

GitHub issues and Milburn events have different jobs:

- GitHub answers: What work exists, and is it blocked, ready, coding, in QA, or done?
- Milburn answers: Which attempt ran, in which tmux window and worktree, and what lifecycle and validation evidence was observed?

Milburn reconciles both views after restart and never silently creates two active Coder attempts for one issue.

### 8.1 GitHub MCP authority boundary

Milburn uses a GitHub MCP server as the initial transport for structured GitHub reads and writes. The MCP connection belongs to the controller, not to individual agents.

Agents submit role-specific requests:

```text
Architect   → submit_issue_drafts
Coder       → report_progress or submit_candidate
Tester      → submit_qa_report
Coordinator → request a read-only status explanation
```

Controller code validates each request, checks repository and role policy, records an effect ID, invokes an allow-listed MCP tool, reads the remote result back, and records the observed outcome. Agents never receive arbitrary issue-close, label-change, merge, or repository-administration authority.

MCP standardizes tool invocation but does not guarantee exactly-once execution. Every GitHub mutation therefore requires an idempotency marker and reconciliation before retry.

### 8.2 Required issue content

Every implementation issue contains an objective, links to relevant specs, acceptance criteria, expected components, dependencies, test instructions, risks, non-goals, and required artifacts.

### 8.3 Recommended labels

```text
milburn:task
milburn:ready
milburn:in-progress
milburn:blocked
milburn:qa
milburn:changes-requested
milburn:done
milburn:decision-needed
```

### 8.4 Ownership rules

- The Architect drafts issues; controller code validates and creates them.
- The controller marks an issue ready only after dependencies are done.
- A Coder works only on its assigned issue and cannot close or self-approve it.
- The Tester supplies QA evidence.
- The controller applies final labels and closure.

## 9. Long-running Coder protocol

This protocol adapts Anthropic's [Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents). Anthropic uses a feature list, progress file, Git history, incremental work, and end-to-end testing. Milburn uses GitHub issues as the task list and adds controller enforcement.

### 9.1 Durable progress file

Each issue branch contains:

```text
.milburn/issues/<issue-number>/progress.txt
```

The file is committed to the issue branch so the latest completed handoff survives a process or controller crash.

### 9.2 Required startup sequence

Before editing product code, every new or resumed Coder must:

1. Confirm repository, worktree, branch, base SHA, attempt ID, and issue number.
2. Read repository instructions such as `AGENTS.md`.
3. Read the assigned issue, dependencies, and recent comments.
4. Read the issue's `progress.txt` if it exists.
5. Inspect Git status and every uncommitted change.
6. Read branch history and search feature-specific history using `[#<issue-number>]`.
7. Review the diff from base SHA to current HEAD.
8. Run the configured smoke check.
9. Compare acceptance criteria with code, progress, commits, and tests.
10. Choose one incomplete criterion or coherent next step; do not redo verified work.

A progress claim is evidence to verify, not a fact to trust blindly.

### 9.3 Required working behavior

The Coder works on one issue, makes incremental changes, updates `progress.txt` after meaningful checkpoints and before handoff, makes coherent commits containing `[#<issue-number>]`, records decisions and tests, avoids unrelated cleanup, and reports blockers instead of guessing.

### 9.4 `progress.txt` format

```text
Issue: #123
Branch: milburn/issue-123
Base revision: <sha>
Current head: <sha>
Last updated: <ISO-8601 time>
Agent attempt: <attempt-id>

Goal
<issue objective>

Completed
- <verified step and commit>

In progress
- <current work and whether the worktree is clean>

Next
1. <smallest useful next action>

Decisions and assumptions
- <decision, reason, and source>

Files changed
- <path>: <purpose>

Validation
- <command or check>: <pass/fail/not run and evidence>

Blockers
- <blocker or "none">

Handoff note
<what a fresh Coder should learn first>
```

### 9.5 Controller enforcement

Before accepting a Coder result, Milburn verifies that issue and attempt IDs match, branch and worktree match, `progress.txt` names the issue and attempt, the claimed commit is reachable, code-changing commits carry the issue marker, test evidence exists or is explicitly blocked, and the Coder did not self-approve.

Failure becomes a protocol error, not a completed implementation.

### 9.6 Crash recovery

1. Mark a missing attempt `unknown`, not `dead`.
2. Inspect tmux, process identity, worktree lock, Git state, issue state, and `progress.txt`.
3. Reconnect if the process is proven alive.
4. Reuse its worktree only if the old process is proven stopped.
5. If uncertain, wait, ask the operator, or branch a new worktree from the last safe commit.
6. Require a replacement Coder to run the full startup sequence.

Replacement also requires a current, versioned handoff manifest that matches
the task and Git state, includes exact test and message-sequence evidence, and
exposes every uncertain external effect. A stale, mismatched, unacknowledged,
or uncertainty-hiding manifest is rejected. The manifest never contains a
private transcript or fabricates unavailable state.

## 10. tmux requirements

Every role receives one window. Milburn records session, window, pane, attempt, role, process identity, and worktree. Stable IDs identify endpoints; titles are labels. Sending keys is not proof of success, and lifecycle commands require observed postconditions.

## 11. Tester requirements

The Tester runs in its own window, receives the issue and exact candidate SHA, tests a clean checkout where practical, records commands and evidence, distinguishes product failure from infrastructure failure, and returns `passed`, `changes_requested`, or `decision_needed`.

Failed QA returns the same issue to a Coder. A new issue is created only for a separate defect.

### 11.1 Durable defect feedback

A meaningful defect observation records its repository, task or issue, role,
attempt, session generation when available, candidate SHA, QA result,
discovery phase, severity, concise symptom, evidence, and status. A resolution
correlates the fix commit, resolver authority, concise root cause and resolution
summary, regression command or test, and result evidence.

Defect events replay deterministically into open, resolved, per-task, and
recurring-lesson views. Stable identities make duplicate QA delivery, retries,
and restart reconciliation idempotent. An unresolved blocking defect—or a
resolved blocking defect without regression evidence—prevents task completion.
Failed QA within the assigned scope returns to the same Coder; a separately
scoped defect becomes a linked GitHub issue through controller policy.

Feedback is concise evidence, not model memory. It contains no transcript,
prompt, chain-of-thought, secret, or unbounded command log.

Recurring lessons are bounded and may be included, as short references, in the
launch briefs of later attempts that touch the same area, so a lesson learned
once is not rediscovered by every attempt.

## 12. Durable events

```text
RequestAccepted             RoleRouteProposed       RoleRouteApproved
CoordinatorSessionStarted   UserMessageReceived     DecisionRequested
CoordinatorNotificationQueued DecisionPresented    UserDecisionReceived
DecisionAnswerValidated     SteeringQueued          SteeringDelivered
SteeringAcknowledged        DecisionResolved        AgentLaunchRequested
AgentStarted
AgentUsageObserved          AgentUsageFinalized     AgentUsageUnavailable
SessionObservationRecorded SessionCompactionObserved SessionGenerationStarted
HandoffManifestValidated   SessionReplacementRequested SessionReplacementCompleted
DefectObserved             DefectResolutionProposed DefectResolved
RegressionEvidenceRecorded
PlanAmendmentRequested     PlanAmendmentImpactAssessed
PlanAmendmentApproved      PlanAmendmentRejected
PlanAmendmentApplied       AgentDispatchResumed
PlanReceived                ArchitecturePackageReceived
GitHubIssueCreated          GitHubIssueReady
GitHubEffectRequested       GitHubEffectObserved    GitHubEffectReconciled
CoderAttemptStarted         CoderCheckpointObserved CoderResultReceived
TestingRequested            TestResultReceived      ChangesRequested
IssueApproved               DecisionRequired        AgentStopped
RecoveryStarted             RecoveryCompleted       FeatureCompleted
```

Events are append-only and versioned. Current state is rebuilt by replay.

### 12.1 Token usage observability

Milburn records token usage only through the Codex adapter's semantic result
boundary. It never derives counts from terminal colors, prose, prompts, or
private transcripts. Each observation is associated with a task ID, role,
attempt ID, Codex session or endpoint, and model when those values are
available.

Observations distinguish partial usage, final totals, and explicitly
unavailable usage. Input, output, cached-input, and reasoning token counts are
optional and are stored only when Codex reports them. Milburn never fabricates
missing counts.

Usage observations are append-only and replay into per-attempt, per-task,
per-role, and workflow totals. Observation identities and source semantics make
duplicate delivery idempotent; cumulative partial observations are not added
twice, and a final total reconciles the attempt without double-counting its
earlier partial observations. Replay after restart produces the same summaries.

This telemetry does not add pricing, budgets, cost ceilings, reservations, or
spend-based routing.

### 12.2 Session generations and durable handoff

Milburn records a logical attempt separately from its Codex session
generations. Semantic adapter observations may report session identity,
compaction, and context usage; unsupported observations are explicitly
unavailable. Versioned events retain task, role, attempt, generation, endpoint
or session ID, source version, observation time, and partial-versus-final
status. Duplicate observations and replay do not duplicate session transitions
or usage.

A versioned handoff manifest records role, task and attempt IDs, issue and
acceptance-criteria references, worktree, branch, base and head SHAs, progress,
completed and remaining work, exact tests, open decisions, inbox/outbox
sequences, uncertain effects, and brief/rules digests. Replacement policy
validates that durable evidence before changing generations.

### 12.3 Plan amendments

A user-authorized change to scope, policy, specifications, tasks, dependencies,
waves, acceptance criteria, or dispatch rules becomes a durable pending plan
amendment. While one is pending, the controller accepts no new agent-launch
effect. Each active attempt is explicitly classified as unaffected, needing
steering, required to pause, or required to stop; unaffected attempts retain
their task ownership and session generation.

The amendment records its authority, requested change, affected work, impact
decisions, registry and specification revisions, GitHub effects, and effective
revision. Application uses expected-version concurrency and stable identities,
so retries and replay are idempotent. Restart preserves pending amendments and
the dispatch freeze. Dispatch resumes only after the approved amendment is
committed, remotely merged, and reconciled; no amendment is silently applied or
dropped.

### 12.4 Context discipline

Milburn manages context size as an operating cost in the controller instead of
leaving agents to notice it late.

- **Fresh launches.** Every agent attempt and replacement session starts from a
  controller-generated launch brief and, for a replacement, a validated handoff
  manifest. No launch inherits a parent's or predecessor's conversation history.
- **Bounded briefs.** A brief contains task identity, acceptance criteria, exact
  commands, role rules, and pointers with line ranges to the specification
  sections that apply. It embeds a digest of its sources, is rejected as stale
  when a source changes, and fails closed above a configured size budget rather
  than being silently truncated.
- **Observed start size.** Milburn records each launch's first observed input size
  when Codex reports it, so excess startup context is visible per role and task.
- **Proactive replacement.** When observed context use reaches a configured
  percentage of the model's reported window, or a configured absolute ceiling,
  whichever comes first, the controller may replace the session, but only at a
  quiescent point (no half-complete decision, no uncertain external effect,
  planning state committed) and only from a validated checkpoint. These
  thresholds are operational triggers, not budgets: they carry no price, never
  block work by themselves, and unsupported observations never trigger them.
- **Resumable controller state.** After restart the Coordinator resumes from a
  bounded state digest of open decisions, unread notifications, active attempts,
  ready tasks, and blockers, not by replaying history.

### 12.5 Bounded rework and escalation

Failed QA returns work to the Coder, but rework must converge. For each task the
controller records every QA round's blocking findings, each with a stable
identity, a category, and a location. Automatic rework continues only while the
work converges, and the controller escalates to a user decision through the
Coordinator when any of these holds:

1. a finding recurs, matching an earlier finding recorded as resolved by category
   and location;
2. a round reports no fewer blocking findings than the most recent earlier round
   that had findings;
3. a round introduces a new blocking finding in code the previous fix touched; or
4. a configured maximum number of fix rounds is reached.

Escalation pauses only that task. Only a recorded user decision may accept a
blocking defect as a known limitation. The acceptance records the user's
authority, keeps the defect open as deferred (never represented as fixed), and
links a follow-up issue. A Coder, Tester, Router, or the Coordinator cannot accept
a blocking defect.

### 12.6 Workspace environment and bounded command output

Agents do not each build their own test environment. Milburn prepares or verifies
one shared dependency environment per repository, keyed to its dependency
declaration and kept outside agent worktrees, and exposes a single test-runner
entry point that uses it with the current worktree's source on the path.
Preparation is idempotent, safe when several agents start at once, and fails with
a clear message when it cannot complete.

Commands run on behalf of agents and the Tester return a bounded summary
(command, result, duration, and a durable log reference) plus the failing excerpt
on failure. Full output is kept as a log and is not placed into agent context by
default.

### 12.7 Operator reports and reconciliation

The operator CLI provides a read-only reconcile report comparing the event store,
GitHub issues, worktrees, tmux endpoints, and progress records. It lists
mismatches and the dependency-ready work, reports unknown, never success, when a
source is unreachable, and never changes state. It also provides a usage report
by role, task, model, and attempt that includes launch context size and
compaction counts, derived only from recorded telemetry.

## 13. Requirements

### 13.1 Skill requirements

Milburn v1 ships six Codex skills:

```text
milburn-coordination
milburn-planning
milburn-routing
milburn-architecture
milburn-long-running-coder
milburn-qa
```

Role rules and skills are different. Role rules are short, mandatory authority constraints included in every launch brief. Skills are loadable procedural packages containing `SKILL.md` plus only the references, scripts, templates, or assets needed for specialized work.

Each role profile declares its required skills. Before launch, the controller verifies that every skill and referenced resource exists, validates its metadata, computes a digest, makes it available in the agent workspace, and records the binding in the attempt. Missing or changed required skills block launch rather than silently falling back to generic behavior.

Skills may guide judgment but cannot grant permissions. GitHub mutation, process lifecycle, worktree ownership, routing approval, and completion remain controller-owned.

The skill suite must include:

- Coordinator procedures for intake, decision presentation, unread-event catch-up, and result summaries.
- Planner procedures and a plan template.
- Router role definitions, examples, confidence guidance, and escalation rules.
- Architect PRD, architecture, ambiguity, lifecycle-design, and issue-decomposition procedures.
- Long-running Coder startup, checkpoint, progress, recovery, and completion procedures.
- Tester acceptance mapping, end-to-end testing, evidence, and defect-classification procedures.
- Generic boundary questions shared by the Coder and Tester skills: what could pass this check while the real condition is false; whether every field and variant of an accepted input is validated or explicitly ignored; whether any entry point can bypass a guard; whether identifiers are unique across the scope where they are used; whether preconditions precede every state change and every failure path leaves state consistent; and whether a test double enforces the same preconditions as the real boundary.
- Negative tests before the happy path for validators and adapters, parity tests for every fake, exhaustive enumeration of a defect class on the first pass, and blast-radius re-testing of fixes before one full confirmation pass.

### 13.2 Testing and evaluation requirements

Milburn uses a test pyramid:

- Fast deterministic unit tests for policy, reducers, state machines, parsing, and effect logic.
- Contract tests for Codex, tmux, GitHub MCP, and Git behavior.
- Scripted-agent integration tests for complete workflows without live model calls.
- Recovery and fault-injection tests at every durable-effect boundary.
- Structural and fixture-based tests for skills.
- A small opt-in live Codex evaluation suite for behavioral quality.

Ordinary unit and integration tests must not launch Codex, tmux, GitHub, or a network connection. They use controllable clocks, deterministic IDs, temporary repositories where needed, and fake implementations of every external boundary.

Live Codex and live GitHub MCP tests run manually or on a protected schedule, not on every commit. Test success must depend on observable artifacts and invariants rather than matching preferred prose.

CI runs unit tests, static checks, skill structural validation, scripted-agent workflows, and local MCP-stub tests on every commit. Pull requests additionally run tmux contracts, temporary-Git tests, and fault-injection suites. Nightly or approved runs exercise live Codex, live GitHub MCP, and the reference end-to-end workflow.

## 14. Cross-cutting functional requirements

- Record intake before launch.
- Maintain one persistent user-facing Coordinator session with durable unread notifications and open decisions.
- Correlate every worker question, user answer, delivery, and worker acknowledgement.
- Accept only known roles and legal transitions.
- Produce `PRD.md` and `ARCH.md` before issues become ready.
- Validate issue content, dependencies, and idempotent creation.
- Execute GitHub mutations through a controller-owned MCP gateway using allow-listed tools, scoped credentials, effect IDs, and read-after-write verification.
- Reconcile an uncertain MCP result before retrying it.
- Give every agent a tmux endpoint and every Coder a worktree.
- Enforce one issue, progress record, and issue-linked commits.
- Require independent Tester evidence.
- Reconcile events with tmux, Git, progress files, and GitHub.
- Let the operator inspect, steer, interrupt, resume, retry, and escalate.

## 15. Acceptance criteria

Version 1 is accepted when:

1. The user interacts with one persistent Codex Coordinator session whose turns end while workers continue.
2. A worker decision is presented in the Coordinator chat and the user's answer returns to the correct worker with correlation and acknowledgement.
3. A Codex Planner plans a request.
4. A Codex Architect creates both specs and at least two dependency-aware issues.
5. The Classifier/Router proposes only legal role transitions.
6. Validated issue drafts are created through GitHub MCP without duplicates after a simulated interrupted response.
7. Agents cannot directly invoke unrestricted GitHub mutation tools.
8. Every agent has a recorded tmux window.
9. A Coder gets exactly one issue and one worktree.
10. A replacement Coder recovers without the prior transcript.
11. Missing or stale progress evidence is rejected.
12. A Tester validates the exact candidate commit.
13. Failed QA returns the issue to coding with evidence.
14. Passed QA lets the controller, not the Coder or Coordinator, mark the issue done.
15. Restarting Milburn preserves unread Coordinator events, open decisions, uncertain MCP effects, and the worker workflow.
16. No budget or multi-harness feature is required.
17. Every agent launch records validated role-rule and required-skill digests.
18. Missing, malformed, or incomplete required skills prevent launch with a clear error.
19. Unit and scripted integration suites run without Codex, tmux, GitHub, or network access.
20. Fault injection proves that crashes do not duplicate issues, launches, decisions, or steering delivery.
21. A protected live evaluation demonstrates Architect ambiguity handling, Coder recovery behavior, Tester independence, and Coordinator decision fidelity.
22. Codex-reported usage replays deterministically into per-attempt, task, role, and workflow totals, with partial and final observations reconciled idempotently and unavailable usage represented explicitly.
23. A logical agent survives fenced replacement sessions through a validated transcript-free handoff manifest; stale manifests, late-generation messages, and unresolved uncertain effects are rejected.
24. Role-specific policy keeps a Coder session for its task attempt by default, ends Planner and Architect at approved artifacts, uses fresh Router calls, and starts every Tester fresh at the exact candidate SHA.
25. Blocking defects prevent completion until resolved with regression evidence; replay and duplicate delivery produce deterministic concise feedback views, while separately scoped defects become linked issues.
26. A mid-run user amendment freezes new launches, preserves unaffected active attempts, applies exactly once at an expected revision, survives restart, and exposes its authority, impact, effective revision, and dispatch status.
27. Every agent launch and replacement starts from a controller-generated brief with a source digest; stale or over-budget briefs are rejected; no launch inherits a transcript; and the launch's observed start size is recorded when reported.
28. A configured context-use percentage or absolute ceiling triggers replacement only at a quiescent point from a validated checkpoint; unsupported observations never trigger it.
29. Rework escalates to a user decision when a finding recurs, a round does not reduce blocking findings, a fix introduces a new blocking finding in touched code, or the maximum number of fix rounds is reached; only a recorded user decision accepts a blocking defect, which stays open as deferred with a linked follow-up issue.
30. Agents and the Tester run tests through one shared, idempotent environment and a bounded command runner that returns summaries with durable log references.
31. The operator CLI produces a read-only reconcile report (unknown when a source is unreachable) and a usage report that includes launch context size and compaction counts.

## 16. Delivery milestones

1. **Coordination skeleton:** event store, replay, workflow guard, tmux runtime, Codex adapter, persistent Coordinator session, and CLI.
2. **Planning and registry:** Coordinator intake, Planner, Router, Architect, specs, issue validation, controller-owned GitHub MCP gateway, and idempotent GitHub creation.
3. **Long-running Coder:** worktrees, startup rules, `progress.txt`, issue-linked commits, recovery drills.
4. **Independent QA:** Tester, clean validation workspace, changes-requested loop, controller completion.
5. **Skills and verification:** six validated skills, deterministic fakes, test pyramid, recovery injection, CI gates, and opt-in live evals.

## 17. Deferred work

Later releases may add multiple harnesses, model selection, usage pricing, budgets, cost ceilings, reservations, spend-based routing, remote runtimes, parallel Coders, pull-request automation, a richer dashboard, and stronger sandboxing. These are intentional future extensions.

Lessons from building Milburn with an agent-coordinated process shape those
extensions. When more harnesses are supported, role assignment becomes a
configured table of harness, model, and effort per role; an unavailable
assignment fails closed with a logged reason and never falls back silently;
reviewing and testing agents use a different model or harness than the author
where available; and each attempt records its harness and model. Plan amendments
may also narrow the dispatch freeze to the affected work, drop independent
review of the amendment record, and derive effectiveness from version-control
history instead of a second reconciliation record.
