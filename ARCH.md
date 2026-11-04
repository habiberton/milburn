# Milburn Architecture Specification

**Status:** Greenfield v1 architecture

**Product:** Milburn

**Initial harness:** Codex only

**Companion document:** `PRD.md`

## 1. Architecture summary

Milburn v1 is a local control plane for six specialized Codex roles. A persistent Coordinator provides the single user-facing chat while a deterministic controller retains authority. The controller advances an allowed workflow, records lifecycle facts, starts each Codex process in its own tmux window, isolates Coder changes in Git worktrees, uses GitHub issues as the task registry, and requires a separate Tester before completion.

```text
                              ┌──────────────────┐
                              │     Operator     │
                              └────────┬─────────┘
                                       │ one continuing chat
                              ┌────────▼─────────┐
                              │ Codex Coordinator│
                              └────────┬─────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Milburn deterministic controller                 │
│ Intake → state machine → transition guard → scheduler → supervisor  │
│                 │                 │                  │               │
│                 ▼                 ▼                  ▼               │
│          Event store       GitHub MCP gateway   tmux + worktrees     │
└──────────────────────────────────────┬──────────────────────────────┘
                                       │ bounded launches
                                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Codex agent plane: one window each               │
│ Coordinator  Planner  Classifier/Router  Architect  Coder  Tester   │
└──────────────────────────────────────┬──────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ PRD.md · ARCH.md · issues · commits · progress.txt · QA · events    │
└─────────────────────────────────────────────────────────────────────┘
```

## 2. Architectural decisions

### 2.1 Codex only

Version 1 has one harness adapter: `CodexAdapter`. Routing chooses a role, not a harness or provider. The adapter boundary remains for future expansion, but no other adapter belongs in v1.

### 2.2 No budget subsystem

The controller does not accept price limits, estimate costs, reserve funds, or reconcile usage. Command and event schemas contain no placeholder budget fields. Budgeting can later be added as a separate policy service.

### 2.3 Every agent runs in tmux

Coordinator, Planner, Classifier/Router, Architect, Coder, and Tester are Codex processes in dedicated tmux windows. Deterministic checks remain ordinary controller functions.

The Coordinator window is logically persistent. Its individual model turns end while workers continue. Actionable events wake a new Coordinator turn; routine progress remains silent.

### 2.4 Two durable records with distinct jobs

- GitHub issues define and display implementation tasks and their workflow status.
- Milburn events record agent attempts, tmux endpoints, worktrees, commands, recovery, and validation.

A reconciler compares them after restart and asks for a decision when they conflict.

### 2.5 Durable artifacts replace transcript handoff

A replacement Coder receives the issue, specs, worktree, `progress.txt`, Git history, and current diff. It does not receive the prior private Codex transcript.

### 2.6 Recommendations are not authority

The Router proposes a role and the Tester supplies QA evidence. The deterministic transition guard and completion policy decide what may happen.

### 2.7 GitHub uses a controller-owned MCP gateway

The initial `GitHubGateway` implementation is an MCP client connected to a GitHub MCP server. Agents do not receive unrestricted GitHub mutation tools. They submit narrow Milburn commands, and controller code validates, authorizes, records, invokes, and reconciles each external effect.

MCP is the transport boundary, not the policy or durability boundary. An MCP timeout is an uncertain outcome until Milburn reads GitHub state and determines whether the requested effect occurred.

## 3. System boundaries

### 3.1 Controller owns

- Command validation and event appends.
- Workflow transitions and scheduling.
- Agent launch, steering, interruption, and retirement.
- tmux identity and worktree ownership.
- GitHub synchronization and idempotency.
- GitHub MCP connection ownership, tool allow-listing, effect journaling, and reconciliation.
- Coder protocol checks.
- QA acceptance and completion.

The controller also owns the durable correlation between a worker question, the Coordinator presentation, the user's answer, and the worker acknowledgement.

### 3.2 Coordinator owns

The Coordinator owns conversational presentation: understanding the user's request, explaining status, presenting worker questions, collecting answers, and summarizing results. It submits bounded commands to the controller and cannot directly launch processes, mutate GitHub, or approve completion.

### 3.3 Other Codex agents own

Bounded language-and-tool tasks. Each instance has one role and one expected result. Agents cannot launch peers directly.

### 3.4 Runtime owns

tmux endpoint creation and control, process inspection, and verified lifecycle postconditions. Sending input alone is not proof of success.

### 3.5 Workspace owns

Mutating Coders receive dedicated worktrees. Tester validates a clean checkout of the exact candidate commit where practical.

## 4. Workflow state machines

Feature state:

```text
received → planning → architecture → issues_ready
         → implementation → testing → completed

Any active state may become decision_needed, blocked, failed, or cancelled.
```

Issue state:

```text
draft → blocked | ready → coding → qa → passed → done
                            ↑       │
                            └───────┘ changes_requested
```

Allowed role transitions:

| Input | Allowed next role |
|---|---|
| New user request | Coordinator intake, then Planner or operator decision |
| Accepted plan | Architect |
| Ready issue | Coder |
| Candidate commit | Tester |
| QA changes requested | Coder |
| QA reports design conflict | Architect or operator |
| Ambiguous route | Operator |

## 5. Components

### 5.1 Intake service

Normalizes the request, binds repository and base branch, assigns request and feature IDs, records delivery posture, and appends `RequestAccepted`.

### 5.2 Coordinator session manager

Maintains one primary Codex Coordinator endpoint per Milburn home. It:

- Restores or launches the Coordinator tmux window.
- Delivers user messages and actionable operational events.
- Tracks unread event and open-decision cursors.
- Records which decisions were presented to the user.
- Accepts bounded Coordinator commands such as intake proposals and decision answers.
- Prevents routine worker progress from creating unnecessary model turns.
- Drains unread decisions and results when a closed interface resumes.

The session manager does not permit the Coordinator to invoke runtime or GitHub mutations directly.

### 5.3 Transition guard

A pure deterministic service that rejects unknown roles and illegal state transitions before an agent launches.

### 5.4 Classifier/Router coordinator

1. Render a brief containing current state, latest event, known roles, and allowed transitions.
2. Start a Codex Router in its own window.
3. Collect one `RoleRouteProposal`.
4. Validate it with the transition guard.
5. Record approval, rejection, or escalation.

The proposal contains no shell command, tmux target, credentials, or arbitrary launch arguments.

### 5.5 Planner coordinator

Starts a Codex Planner with the user goal, repository summary, scope, known decisions, and output contract. The Planner returns stages, dependencies, risks, and questions. It does not create issues or launch agents.

### 5.6 Architect coordinator

Starts a Codex Architect with the accepted plan. The Architect creates or updates `PRD.md` and `ARCH.md`, then returns dependency-aware `IssueDraft` objects.

The Architect does not receive unrestricted GitHub credentials. Controller code validates and creates issues using stable idempotency keys.

### 5.7 GitHub registry

Reads issue metadata, creates validated issues, applies configured labels, adds run-linked comments, records dependencies, prevents duplicate creation, advances issue status, and reconciles remote state.

The registry depends on a controller-owned gateway:

```python
class GitHubGateway(Protocol):
    def get_repository(self, repository: RepositoryId) -> Repository: ...
    def list_issues(self, query: IssueQuery) -> tuple[Issue, ...]: ...
    def create_issue(self, command: CreateIssueCommand) -> Issue: ...
    def add_comment(self, command: AddCommentCommand) -> IssueComment: ...
    def set_labels(self, command: SetLabelsCommand) -> Issue: ...
    def close_issue(self, command: CloseIssueCommand) -> Issue: ...
```

`GitHubMcpGateway` is the v1 implementation. It maps these operations to an allow-listed GitHub MCP tool set. The rest of Milburn does not depend on MCP tool names or wire format.

Suggested idempotency key:

```text
milburn:<repository-id>:<feature-id>:<architect-task-key>
```

The key is stored in the issue body or a machine-readable comment and in Milburn events. Every mutation follows this sequence:

```text
validate role-specific command
→ append GitHubEffectRequested(effect_id)
→ reconcile by idempotency marker
→ invoke the allow-listed MCP tool only if absent
→ read GitHub state back
→ append GitHubEffectObserved(remote identity)
```

If the MCP call times out, Milburn does not immediately retry. It searches for the effect marker first. Existing remote state is adopted; absent state permits a retry with the same effect ID; unreadable state remains unresolved.

### 5.8 Agent GitHub permissions

- **Coordinator:** may request bounded read-only status summaries; no direct mutation tools.
- **Planner:** receives controller-prepared repository and issue summaries.
- **Classifier/Router:** receives only workflow facts needed for routing.
- **Architect:** reads bounded issue context and submits `IssueDraft` objects.
- **Coder:** reads its assigned issue and submits progress or candidate commands.
- **Tester:** reads its assigned issue and submits `QAReport`.

Only controller code invokes GitHub mutations through the gateway.

### 5.9 Scheduler

An issue is schedulable only when dependencies are done, no Coder attempt is active, specs and approvals exist, a worktree slot is available, and repository concurrency policy permits it. Version 1 may allow only one active Coder globally.

### 5.10 Worktree manager

Validates the repository, creates branch `milburn/issue-<number>`, creates an attempt worktree, records path/base/branch, prevents simultaneous mutating ownership, preserves evidence, and deletes only controller-created validated paths.

### 5.11 Coder coordinator

Builds a brief from one issue, relevant spec sections, repository instructions, worktree identity, role rules, test instructions, and result contract. It records the hash of the rendered rules.

`CoderProtocolGuard` verifies the progress file, issue-linked commits, claimed SHA, test evidence, and issue ownership before accepting a result.

### 5.12 Tester coordinator

Creates a clean validation workspace at the exact candidate SHA and launches a Codex Tester with the issue, acceptance criteria, specs, test instructions, and Coder evidence clearly labeled as claims. It returns a `QAReport` and does not edit the candidate branch by default.

### 5.13 Supervisor

Combines tmux existence, process identity, Codex semantic state when available, event age, Git and progress activity, and explicit results. It classifies attempts as `starting`, `busy`, `idle`, `waiting`, `unknown`, `stopped`, or `failed`. `unknown` is never automatically safe to replace.

## 6. Codex adapter

```python
class CodexAdapter(Protocol):
    def launch(self, request: LaunchRequest) -> AgentEndpoint: ...
    def steer(self, endpoint: AgentEndpoint, message: SteeringMessage) -> Ack: ...
    def status(self, endpoint: AgentEndpoint) -> AgentStatus: ...
    def interrupt(self, endpoint: AgentEndpoint) -> ControlResult: ...
    def collect(self, endpoint: AgentEndpoint) -> AgentResult: ...
    def retire(self, endpoint: AgentEndpoint) -> ControlResult: ...
```

The adapter owns Codex command syntax, session arguments, permissions, result collection, and semantic status. The controller does not parse terminal colors or treat a prompt as completion.

## 7. tmux runtime

```python
class TmuxRuntime(Protocol):
    def create_window(self, spec: WindowSpec) -> RuntimeEndpoint: ...
    def send_doorbell(self, endpoint: RuntimeEndpoint, token: str) -> SendResult: ...
    def inspect(self, endpoint: RuntimeEndpoint) -> RuntimeObservation: ...
    def interrupt(self, endpoint: RuntimeEndpoint) -> RuntimeObservation: ...
    def terminate(self, endpoint: RuntimeEndpoint) -> RuntimeObservation: ...
```

Endpoint identity includes session, window ID, pane ID, attempt ID, role, generation, process identity, and worktree when applicable. Titles are labels, not identifiers. Generation prevents a delayed command from affecting a replacement process.

## 8. Role rule system

```text
milburn/role_rules/
├── coordinator.md
├── planner.md
├── classifier_router.md
├── architect.md
├── tester.md
└── coder/
    ├── startup.md
    ├── working.md
    └── completion.md
```

`BriefRenderer` combines role rules, task context, repository instructions, and a result contract. The rendered brief and SHA-256 digest are recorded before launch. Rules guide the model; controller code enforces mechanically checkable rules.

### 8.1 Required Codex skill packages

Skills use progressive disclosure: `SKILL.md` contains purpose, routing, essential workflow, and important constraints; detailed schemas and mode-specific guidance live in referenced files; deterministic repeated checks live in scripts. Skills do not duplicate controller policy or generic Codex capabilities.

```text
.agents/skills/
├── milburn-coordination/
│   ├── SKILL.md
│   └── references/
│       ├── decision-presentation.md
│       └── result-summary.md
├── milburn-planning/
│   ├── SKILL.md
│   └── references/
│       ├── plan-template.md
│       └── planning-checklist.md
├── milburn-routing/
│   ├── SKILL.md
│   └── references/
│       └── routing-rules.md
├── milburn-architecture/
│   ├── SKILL.md
│   ├── references/
│   │   ├── prd-template.md
│   │   ├── architecture-template.md
│   │   ├── issue-template.md
│   │   ├── ambiguity-checklist.md
│   │   └── decomposition-rules.md
│   └── scripts/
│       └── validate-specs.py
├── milburn-long-running-coder/
│   ├── SKILL.md
│   ├── references/
│   │   ├── startup-checklist.md
│   │   ├── progress-template.txt
│   │   └── completion-checklist.md
│   └── scripts/
│       └── verify-handoff.py
└── milburn-qa/
    ├── SKILL.md
    ├── references/
    │   ├── qa-report-template.md
    │   ├── acceptance-testing.md
    │   └── defect-classification.md
    └── scripts/
        └── validate-qa-report.py
```

Skill responsibilities:

- `milburn-coordination`: turn user language into bounded intake, explain worker questions without changing their meaning, correlate answers, and summarize verified outcomes.
- `milburn-planning`: identify stages, dependencies, risks, decisions, and appropriate architecture work without launching agents or creating issues.
- `milburn-routing`: select one known role, explain why, report confidence, and escalate ambiguity; it cannot authorize the transition.
- `milburn-architecture`: perform discovery, request consequential decisions, create aligned PRD and architecture documents, design project lifecycle commands, and draft independently testable issues.
- `milburn-long-running-coder`: recover from durable evidence, work one issue incrementally, maintain `progress.txt`, create issue-linked commits, test, and leave a clean handoff.
- `milburn-qa`: validate the exact candidate SHA, map every acceptance criterion to evidence, distinguish product from infrastructure failure, and avoid silently fixing the candidate.

### 8.2 Role-to-skill binding

Role configuration declares required skills:

```yaml
roles:
  coordinator:
    required_skills: [milburn-coordination]
  planner:
    required_skills: [milburn-planning]
  classifier_router:
    required_skills: [milburn-routing]
  architect:
    required_skills: [milburn-architecture]
  coder:
    required_skills: [milburn-long-running-coder]
  tester:
    required_skills: [milburn-qa]
```

`SkillCatalog` validates names, frontmatter, referenced resources, and executable helpers before an attempt starts. It copies or mounts the approved skill into the workspace, explicitly names it in the launch brief, and records a `SkillBinding` containing name, version, root digest, and resource digests. A resumed or replacement attempt receives the current approved binding; a changed digest is visible as a new launch fact.

### 8.3 Skill authority boundary

A skill is instruction, not authority. It cannot grant a role GitHub mutation access, process-control access, a different worktree, completion rights, or permission to bypass an approval. Mechanically enforceable rules remain in controller policy and validation code. Skill scripts operate on bounded local inputs and must be tested before release.

### 8.4 Skill validation

Every skill receives:

- Structural validation for metadata, naming, missing references, missing scripts, and unfinished placeholders.
- Fixture-based behavioral checks using realistic inputs and result-contract validation.
- Independent forward evaluations for complex behavior without revealing the expected answer to the evaluated agent.
- Version and digest checks in launch contract tests.

Tests assess artifacts and invariants, not exact wording.

## 9. Long-running Coder design

### 9.1 Progress path

```text
<worktree>/.milburn/issues/<issue-number>/progress.txt
```

It is issue-specific and committed to the issue branch.

### 9.2 Startup algorithm

```text
verify attempt, issue, repository, worktree, branch, and base
read AGENTS.md and repository guidance
read the issue, dependencies, and comments
read PRD.md and ARCH.md references
read progress.txt
inspect git status and uncommitted changes
search git log for [#<issue-number>]
inspect branch history and base..HEAD diff
run the configured smoke test
compare evidence with acceptance criteria
select one coherent next action
```

### 9.3 Checkpoint checks

Before a result is accepted:

```text
progress issue == assigned issue
progress attempt == active attempt
progress current head == claimed head
claimed head is reachable from the recorded branch
code-changing work has an issue-linked commit
test evidence is present or explicitly blocked
```

### 9.4 Recovery algorithm

```text
project the active attempt from events
inspect tmux endpoint and process
inspect worktree lock, Git status, progress.txt, and GitHub issue

if process is proven alive:
    reconnect supervision
elif process is proven stopped:
    record recovery, increment generation, launch replacement
else:
    mark unknown and wait, escalate, or create a new worktree
```

The replacement always runs the full startup algorithm.

### 9.5 Relationship to Anthropic's pattern

Milburn adopts the durable progress file, Git history, incremental single-feature work, repeatable startup, clean handoff, and explicit end-to-end testing from Anthropic's [long-running agent research](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents).

Milburn changes the pattern by using GitHub issues instead of a local feature-list file, assigning initial decomposition to the Architect, assigning final QA to a separate Tester, and enforcing handoff rules in controller code.

## 10. Data contracts

Open-ended work remains prose. Durable facts use small typed envelopes.

```text
RequestEnvelope
  request_id, feature_id, objective, repository_id, base_branch,
  delivery_posture, submitted_at

RoleRouteProposal
  request_id, current_state, proposed_role, reason, confidence,
  decision_needed

DecisionRequest
  decision_id, source_attempt_id, feature_id, issue_number, question,
  why_it_matters, options, recommendation, blocking

UserDecision
  decision_id, coordinator_attempt_id, selected_option, answer,
  answered_by, answered_at

CoordinatorNotification
  notification_id, kind, correlation_id, priority, summary,
  unread, created_at

PlanEnvelope
  feature_id, summary, stages, dependencies, risks, decisions_needed

ArchitecturePackage
  feature_id, prd_artifact, arch_artifact, issue_drafts, open_decisions

IssueDraft
  task_key, title, objective, spec_links, acceptance_criteria,
  dependencies, test_instructions, expected_artifacts, risks, non_goals

GitHubEffect
  effect_id, repository_id, operation, idempotency_marker,
  requested_arguments_digest, status, remote_identity, last_observation

AgentAttempt
  attempt_id, generation, role, feature_id, issue_number, endpoint,
  worktree, branch, base_sha, rules_digest, skill_bindings, status

SkillBinding
  skill_name, version, root_digest, resource_digests,
  workspace_path, validated_at

CoderResult
  attempt_id, issue_number, outcome, head_sha, progress_path,
  commits, files_changed, test_claims, risks

QAReport
  attempt_id, issue_number, candidate_sha, outcome,
  acceptance_results, commands, evidence_artifacts, defects, summary
```

## 11. Event streams and order

Suggested streams:

```text
feature:<feature-id>
issue:<repository-id>:<issue-number>
agent:<attempt-id>
runtime:<attempt-id>
github:<repository-id>
effect:github:<effect-id>
coordinator:<milburn-home-id>
decision:<decision-id>
```

Typical issue sequence:

```text
GitHubIssueReady → RoleRouteProposed → RoleRouteApproved
→ CoderAttemptRequested → WorktreeCreated → AgentLaunchRequested
→ AgentStarted → CoderCheckpointObserved* → CoderResultReceived
→ TestingRequested → TesterStarted → TestResultReceived
→ IssueApproved | ChangesRequested | DecisionRequired
```

Commands request effects; events record observed facts. `AgentStarted` is appended only after start evidence is observed.

GitHub mutation sequence:

```text
GitHubEffectRequested → GitHubEffectReconciled
→ GitHubMcpCallStarted → GitHubEffectObserved | GitHubEffectUncertain
```

Coordinator decision sequence:

```text
DecisionRequested → CoordinatorNotificationQueued
→ DecisionPresented → UserDecisionReceived
→ DecisionAnswerValidated → SteeringQueued
→ SteeringDelivered → SteeringAcknowledged
→ DecisionResolved → AgentResumed
```

## 12. Steering and lifecycle control

Full steering messages are written to:

```text
<milburn-home>/inboxes/<attempt-id>/<sequence>.json
```

Milburn sends only a short doorbell token to the window. Lifecycle operations are separately allow-listed: `interrupt`, `terminate`, `resume`, `replace`, and `retire`. Each requires an observed postcondition.

### 12.1 Coordinator wake and reply path

The Coordinator does not keep one model turn loading while workers run. Its turn ends after acknowledgement or reporting. `CoordinatorSessionManager` watches the durable notification queue and starts a new Coordinator turn only for actionable items.

For a worker question:

1. The worker publishes a structured `DecisionRequest` to its outbox.
2. The controller validates it, records it, marks the worker `waiting_user`, and queues a Coordinator notification.
3. The session manager writes the notification to the Coordinator inbox and sends a doorbell to its tmux endpoint.
4. The Coordinator explains the decision in the user chat and reports `DecisionPresented`.
5. The user's next message is correlated with the open decision. The Coordinator submits a `UserDecision` command to the controller.
6. The controller validates and records the answer, writes it to the originating worker's inbox, and sends that worker a doorbell.
7. The worker acknowledges the message before the decision is resolved and work resumes.

If the user interface or Coordinator session is unavailable, the notification remains unread. A resumed or replacement Coordinator drains open decisions and terminal results from durable state before handling unrelated conversation.

## 13. Failure handling

- **Codex exits without a result:** preserve worktree and progress; record exit separately from task failure.
- **Progress evidence missing:** reject at `CoderProtocolGuard`; do not mark complete.
- **GitHub MCP unavailable:** keep a pending effect and retry with the same effect ID only after the server and repository can be read again.
- **GitHub MCP mutation times out:** mark the effect uncertain, search GitHub for its idempotency marker, and never assume either success or failure.
- **MCP tool set changes:** fail startup compatibility checks if required allow-listed tools or expected argument fields are unavailable.
- **Tester infrastructure fails:** return `failed`, not `changes_requested`, unless product evidence exists.
- **Specs and issue conflict:** pause and route to Architect or operator.
- **tmux endpoint missing:** mark `unknown` until process and workspace evidence are reconciled.
- **Coordinator unavailable:** retain unread notifications and open decisions; workers remain in `waiting_user` and are not treated as failed.
- **Coordinator answer is ambiguous:** keep the decision open and ask the user to clarify rather than guessing which worker instruction to send.

## 14. Security model

tmux organizes processes and worktrees isolate changes; neither is a security sandbox. The GitHub MCP credential is owned by the controller, restricted to selected repositories, and initially limited to metadata read, issue read/write, pull-request read, and checks read. Merge, release, administration, and repository-content write permissions are excluded from v1. Secrets never enter briefs, progress files, issues, events, or terminal captures. Repository and issue text are untrusted data, and destructive or publishing actions require policy approval.

## 15. Observability

The operator can answer which feature and issue are active, which role is running and why, which tmux endpoint and process belong to it, which worktree and SHAs are involved, when progress last changed, which issue-linked commits exist, what QA found, whether the attempt is busy, waiting, unknown, stopped, or failed, which Coordinator notifications remain unread, and which decisions are still open.

## 16. Proposed source tree

```text
milburn/
├── .agents/
│   └── skills/
│       ├── milburn-coordination/
│       ├── milburn-planning/
│       ├── milburn-routing/
│       ├── milburn-architecture/
│       ├── milburn-long-running-coder/
│       └── milburn-qa/
├── config/
│   ├── roles.yaml
│   ├── policies.yaml
│   └── github-labels.yaml
├── docs/
│   ├── operations.md
│   ├── recovery.md
│   └── testing.md
├── pyproject.toml
├── README.md
├── PRD.md
├── ARCH.md
├── src/
│   └── milburn/
│       ├── app/
│       │   ├── cli.py
│       │   ├── bootstrap.py
│       │   └── configuration.py
│       ├── domain/
│       │   ├── commands.py
│       │   ├── events.py
│       │   ├── models.py
│       │   ├── states.py
│       │   ├── policies.py
│       │   └── errors.py
│       ├── orchestration/
│       │   ├── controller.py
│       │   ├── workflow.py
│       │   ├── scheduler.py
│       │   ├── coordinator.py
│       │   ├── notifications.py
│       │   ├── supervisor.py
│       │   └── reconciliation.py
│       ├── agents/
│       │   ├── codex_adapter.py
│       │   ├── briefs.py
│       │   ├── result_parser.py
│       │   ├── skill_catalog.py
│       │   └── role_rules/
│       │       ├── coordinator.md
│       │       ├── planner.md
│       │       ├── classifier_router.md
│       │       ├── architect.md
│       │       ├── tester.md
│       │       └── coder/
│       │           ├── startup.md
│       │           ├── working.md
│       │           └── completion.md
│       ├── runtime/
│       │   ├── tmux.py
│       │   ├── processes.py
│       │   ├── worktrees.py
│       │   └── messaging.py
│       ├── integrations/
│       │   ├── mcp/
│       │   │   ├── client.py
│       │   │   └── effects.py
│       │   └── github/
│       │       ├── gateway.py
│       │       ├── registry.py
│       │       └── contracts.py
│       ├── persistence/
│       │   ├── sqlite_store.py
│       │   ├── projections.py
│       │   └── migrations/
│       ├── validation/
│       │   ├── coder_protocol.py
│       │   ├── issue_contracts.py
│       │   ├── qa_policy.py
│       │   └── skill_validation.py
│       └── observability/
│           ├── logging.py
│           └── operator_views.py
└── tests/
    ├── fakes/
    │   ├── clock.py
    │   ├── ids.py
    │   ├── event_store.py
    │   ├── codex.py
    │   ├── tmux.py
    │   ├── github.py
    │   └── mcp.py
    ├── fixtures/
    │   ├── agents/
    │   ├── skills/
    │   ├── repositories/
    │   └── workflows/
    ├── unit/
    │   ├── domain/
    │   ├── orchestration/
    │   ├── agents/
    │   ├── runtime/
    │   ├── integrations/
    │   ├── persistence/
    │   └── validation/
    ├── contract/
    │   ├── codex/
    │   ├── tmux/
    │   └── github_mcp/
    ├── integration/
    │   └── workflows/
    ├── recovery/
    ├── skills/
    └── evals/
```

No budget module, provider registry, or non-Codex adapter belongs in v1.

## 17. Required tests

### 17.1 Test framework and determinism

The default test stack is `pytest`, `pytest-timeout`, and `pytest-xdist`; `hypothesis` is recommended for reducer and state-machine invariants once the basic suite is stable. Tests use a controllable clock, deterministic ID source, temporary directories, and explicit random seeds. Unit tests never sleep or depend on wall-clock timing.

Ordinary unit and scripted integration tests must not launch Codex, tmux, GitHub, or a network connection. External boundaries are injected through protocols and replaced with:

```text
FakeClock
DeterministicIdGenerator
InMemoryEventStore
FakeCodexAdapter
FakeTmuxRuntime
FakeGitHubGateway
FakeMcpClient
FakeNotificationQueue
FakeWorktreeManager
```

### 17.2 Unit tests

Unit tests cover one policy or state transition at a time:

| Package | Required coverage |
|---|---|
| `domain` | Event versions, serialization, command validation, legal and illegal states |
| `orchestration` | Scheduling, dependencies, decision correlation, notification cursors, reconciliation choices |
| `agents` | Brief assembly, result parsing, role/skill binding, digest recording |
| `runtime` | Endpoint parsing, generation protection, safe paths, inbox sequencing |
| `integrations.mcp` | Tool discovery, argument mapping, timeout/error classification, effect states |
| `integrations.github` | Issue contracts, idempotency markers, read-after-write, uncertain-effect reconciliation |
| `persistence` | Expected sequence, replay determinism, migrations, concurrent append rejection |
| `validation` | Progress parsing, commit markers, candidate SHA, QA evidence, skill structure |

Core controller, state-machine, event-store, effect-journal, and validation branches target at least 90% branch coverage. Coverage is a diagnostic; required behavioral invariants remain the release gate.

### 17.3 Skill tests

Skill tests include:

- Structural validation of frontmatter, names, references, scripts, and unfinished placeholders.
- Fixture-based checks against realistic new-repository, ambiguous-requirement, failed-QA, and recovery cases.
- Script tests for `validate-specs.py`, `verify-handoff.py`, and `validate-qa-report.py`.
- Launch contract tests proving required skill availability and digest recording.
- Independent forward evaluations for complex skills without supplying the expected answer to the evaluated agent.

Tests validate artifacts and invariants rather than exact generated wording.

### 17.4 Scripted-agent integration tests

`ScriptedAgent` fixtures return predetermined `PlanEnvelope`, `ArchitecturePackage`, `CoderResult`, `DecisionRequest`, and `QAReport` objects. These tests exercise complete workflows without model calls:

- Coordinator intake through plan and issue creation.
- Architect question through user answer and acknowledgement.
- Ready issue through Coder candidate and Tester pass.
- Failed QA through changes requested and replacement Coder.
- Controller restart with unread Coordinator events and active work.

### 17.5 Contract tests

- **Codex:** launch, steer, status, interrupt, collect, and retire with observed postconditions.
- **tmux:** stable window IDs, duplicate titles, generation isolation, missing endpoints, and termination proof.
- **GitHub MCP:** tool discovery, schema compatibility, result conversion, timeout classification, read-after-write, and idempotency reconciliation against a local stub server.
- **Git:** branch/worktree creation, issue-linked commit search, uncommitted changes, and safe cleanup in temporary repositories.

Live GitHub MCP compatibility uses a dedicated test repository and protected credentials; it is not required on every commit.

### 17.6 Recovery and fault injection

The suite deliberately stops the controller after each important boundary:

```text
after GitHubEffectRequested, before the MCP call
after the MCP call, before the remote identity is recorded
after issue creation, before read-after-write completes
after worker inbox write, before the doorbell
after the doorbell, before acknowledgement
after a Coder commit, before progress update
after progress update, before result collection
after Tester pass, before issue closure
```

Restart must not duplicate issues, launches, user decisions, unsafe steering, or completion. It must not reuse a possibly live worktree or discard an uncertain external effect.

### 17.7 Live Codex evaluations

An opt-in suite evaluates behavior that deterministic tests cannot prove:

- Architect asks about consequential ambiguity but avoids unnecessary questions.
- Architect produces aligned specs and agent-sized issues.
- Coder follows startup recovery, updates progress, and avoids unrelated work.
- Tester remains independent and distinguishes infrastructure failure.
- Coordinator preserves the meaning, options, and recommendation of worker questions.
- Router selects only known roles and escalates low-confidence ambiguity.

These evaluations run manually or on a protected schedule with bounded fixtures, isolated workspaces, and explicit cost limits. They never receive production credentials.

### 17.8 CI gates

Every commit runs unit tests, static analysis, formatting checks, skill structural validation, scripted-agent workflows, and local MCP-stub tests. Pull requests additionally run tmux contracts, temporary-Git contracts, recovery tests, and fault injection. Nightly or manually approved workflows run live Codex evaluations, live GitHub MCP compatibility, and the full reference application workflow.

## 18. Implementation order

1. Define command, event, feature, issue, attempt, and result contracts.
2. Build event store and replay.
3. Build workflow state machine and transition guard.
4. Build tmux runtime and verified postconditions.
5. Build Codex adapter and live contract tests.
6. Build role-rule rendering, `SkillCatalog`, skill validation, role bindings, and digest recording.
7. Create and fixture-test the six required skill packages.
8. Build the persistent Coordinator session, notification queue, and decision round trip.
9. Build the controller-owned MCP client, GitHub gateway, effect journal, registry, and reconciliation.
10. Build Planner and Router coordinators.
11. Build Architect and issue validation.
12. Build worktree manager and Coder coordinator.
13. Build protocol guard and progress watcher.
14. Build Tester and QA policy.
15. Add recovery drills, fault injection, CI gates, live evaluations, and operator views.

## 19. Definition of architectural completion

```text
user request in the persistent Coordinator chat
→ controller-accepted intake
→ skill-bound Coordinator, Planner, Router, Architect, Coder, and Tester attempts
→ plan
→ PRD.md and ARCH.md
→ dependency-aware GitHub issues created through the controller-owned MCP gateway
→ one isolated Coder attempt per ready issue
→ durable progress.txt and issue-linked commits
→ independent Tester evidence
→ controller-approved completion
→ Coordinator-delivered result
```

Every step remains understandable after restart and without access to prior private transcripts. Deterministic tests cover policy and recovery, while protected live evaluations cover model behavior that cannot be proven with fixtures.
