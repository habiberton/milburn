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

Version 1 supports only Codex. It does not choose among Codex, Claude Code, OpenCode, or model providers. It also omits monetary budgets. This keeps the first engineering problem focused on reliable coordination between a primary controller and worker agents.

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

## 5. Non-goals

Version 1 will not support another harness, select models, enforce budgets, run a distributed fleet, require a permanent server, automatically merge or deploy, copy private transcripts between roles, trust Coder test claims as final QA, infer success from process exit, or give agents unrestricted GitHub MCP mutation tools. tmux and worktrees are not security sandboxes.

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

## 10. tmux requirements

Every role receives one window. Milburn records session, window, pane, attempt, role, process identity, and worktree. Stable IDs identify endpoints; titles are labels. Sending keys is not proof of success, and lifecycle commands require observed postconditions.

## 11. Tester requirements

The Tester runs in its own window, receives the issue and exact candidate SHA, tests a clean checkout where practical, records commands and evidence, distinguishes product failure from infrastructure failure, and returns `passed`, `changes_requested`, or `decision_needed`.

Failed QA returns the same issue to a Coder. A new issue is created only for a separate defect.

## 12. Durable events

```text
RequestAccepted             RoleRouteProposed       RoleRouteApproved
CoordinatorSessionStarted   UserMessageReceived     DecisionRequested
CoordinatorNotificationQueued DecisionPresented    UserDecisionReceived
DecisionAnswerValidated     SteeringQueued          SteeringDelivered
SteeringAcknowledged        DecisionResolved        AgentLaunchRequested
AgentStarted
PlanReceived                ArchitecturePackageReceived
GitHubIssueCreated          GitHubIssueReady
GitHubEffectRequested       GitHubEffectObserved    GitHubEffectReconciled
CoderAttemptStarted         CoderCheckpointObserved CoderResultReceived
TestingRequested            TestResultReceived      ChangesRequested
IssueApproved               DecisionRequired        AgentStopped
RecoveryStarted             RecoveryCompleted       FeatureCompleted
```

Events are append-only and versioned. Current state is rebuilt by replay.

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

## 16. Delivery milestones

1. **Coordination skeleton:** event store, replay, workflow guard, tmux runtime, Codex adapter, persistent Coordinator session, and CLI.
2. **Planning and registry:** Coordinator intake, Planner, Router, Architect, specs, issue validation, controller-owned GitHub MCP gateway, and idempotent GitHub creation.
3. **Long-running Coder:** worktrees, startup rules, `progress.txt`, issue-linked commits, recovery drills.
4. **Independent QA:** Tester, clean validation workspace, changes-requested loop, controller completion.
5. **Skills and verification:** six validated skills, deterministic fakes, test pyramid, recovery injection, CI gates, and opt-in live evals.

## 17. Deferred work

Later releases may add multiple harnesses, model selection, budgets, remote runtimes, parallel Coders, pull-request automation, a richer dashboard, and stronger sandboxing. These are intentional future extensions.
