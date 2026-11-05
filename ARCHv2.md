# Milburn Architecture v2 (draft additions)

**Status:** Draft. Not approved. Does not change `ARCH.md` or any build task.

**Relationship to v1:** These are additions to `ARCH.md` (v1) that implement
`PRDv2.md`. v1 stays authoritative for everything not named here. "v1 §5.7" means
`ARCH.md`. Where this document and v1 conflict, stop and ask the user. Decision IDs
here start with `D2-`; requirement IDs `V2-` are defined in `PRDv2.md`.

## 1. Summary

Two stages, Discovery and Design, are added ahead of the Architect. Both use the
existing authority model: Codex roles produce artifacts and proposals, and
deterministic controller policy decides whether a gate passes. The structural change
that makes this cheap is a stage table (D2-1), so new stages are data and not new
controller code.

```text
Intake → Router → [ Discovery → grill gate ] → Planner → [ Design → approval ]
       → Architect → Scheduler → Coder → Tester → completed
         (brackets: new stages, table entries)
```

## 2. Decisions

### D2-1. Stages are data

v1's workflow (ARCH §4) is a fixed state machine. v2 expresses it as a **stage table**
that the transition guard (v1 §5.3) evaluates:

| Stage | Role | Required skills | Connectors | Input | Output | Gate | Skip |
|---|---|---|---|---|---|---|---|
| discovery | Discoverer | `milburn-discovery` | research gateway (read) | request, repo summary | `DiscoveryBrief` (rendered as the change's `proposal.md`), ledger | grill gate | policy or user |
| planning | Planner | `milburn-planning` | none | `DiscoveryBrief` | plan | plan accepted | none |
| design | Designer | `milburn-design`, `frontend-design` (vendored), project design system | render service | plan, brief, references | `DesignVariantSet`, `DesignSpec` | design approval | not user-facing, or user |
| architecture | Architect | v1 skills, `milburn-spec` | spec tool (controller-owned; read-only wrapper for the agent) | plan, brief, `DesignSpec` | specs, spec change, issue drafts | v1 plus design binding, spec validation, requirement-ID citation | none |
| implementation, testing | v1 | v1 | v1 | v1 | v1 | v1 | none |

The default table with Discovery and Design disabled reproduces v1 exactly (V2 AC 12).
The table is validated at startup: unknown roles, missing skills, unreachable stages,
and cycles are rejected. Adding a stage never edits controller core.

### D2-2. The controller owns the question ledger

Questions and their resolutions are controller state, not agent output. The Discoverer
submits `QuestionProposal` and `AnswerProposal` commands; a question changes status
only through a validated command, and `answered` or `assumed` require a referenced
`UserDecision` (v1 §12.1 decision path). This keeps the grill gate unfakeable by the
agent being graded.

### D2-3. Research is read-only, gateway-mediated, and provenance-checked

Research goes through `ResearchGateway`, a sibling of `GitHubGateway` with the same
discipline: allow-listed operations, effect IDs, recorded outcomes, no agent-held
credentials. It exposes search and fetch only. Every fetched document is stored as a
bounded snapshot with a content digest. A `ResearchFinding` is accepted only if its
quote appears verbatim in its snapshot. Unreachable sources are recorded as
`unavailable`. Retrieved text is untrusted data and never reaches a role as
instructions.

### D2-4. Design artifacts are repository files plus events

Variants and the final spec are files in a feature directory, committed to the feature
branch, so they survive restarts and are reviewable in Git. Events record identities
and digests; files hold content. Screenshots are produced only by the controller's
`RenderService`, never supplied by the Designer.

### D2-5. Third-party skills are vendored, pinned, and digest-bound

A third-party skill such as Anthropic's `frontend-design` is copied into the repository
with its license, upstream source and commit, retrieval date, and digest. Milburn's
existing skill validation (v1 §8.4) computes and records the digest at launch. Nothing
is fetched at launch. A skill with no confirmed redistributable license is not
vendored.

### D2-6. OpenSpec is a pinned, controller-owned external tool, not a fork

Milburn uses OpenSpec's layout and CLI for the target repository's specs (PRDv2 §6).
It is not forked. Everything Milburn needs differently is expressed through a project
schema, configuration, and a wrapper. The controller installs or verifies a pinned
build at init and records its version and digest. No role runs the CLI directly: the
controller calls it through `SpecToolGateway`, and agents get a read-only subset
through Milburn commands. Facts verified against 1.16.0: MIT license; Node 22.12 or
newer, or the standalone build; offline operation; writes confined to the project;
telemetry on by default and disabled by environment variable.

### D2-7. Monitoring is a projection of the event store

The stream, logs views, metrics, traces, and alerts hold no authoritative state. They
read the event store (v1 §11) and rebuild by replay. What the store lacks is agent
activity, which a new ingest layer adds by normalizing harness-specific sources into
one vocabulary (D2-8). PRDv2 §8 holds the requirements.

### D2-8. Activity comes from sources in a fixed fidelity order

`ActivityIngest` accepts, in order of preference: a structured stream or telemetry the
harness exposes; the harness's session log, version-gated because its format is not a
documented contract; and environment observations that need no harness cooperation.
Terminal text is display only and never becomes an event. Each event records its source
and fidelity. For Codex this means `codex exec --json` for non-interactive runs, the
`[otel]` export and the session log for agents hosted in tmux, and git, progress-file,
test, and process observations for every agent. A custom harness later implements the
same vocabulary natively. Unverified: the Codex app-server notification protocol, whether
a per-process Codex home directory can be set, and whether metrics export is supported.

### D2-9. Remote access is authenticated, scoped, and never a second authority

The monitor interface serves read and limited control, but every control action becomes
an ordinary controller command, validated by the same policy as a local one. Remote
access is an opt-in exposure of a localhost service through a tunnel or private network
that the user provisions; Milburn includes no relay.

## 3. State machines

Feature state (extends v1 §4):

```text
received → discovery → planning → design → architecture → issues_ready
         → implementation → testing → completed

discovery and design may be skipped on the record.
Any active state may become decision_needed, blocked, failed, or cancelled.
```

Allowed role transitions (extends the v1 table):

| Input | Allowed next role |
|---|---|
| New user request needing discovery | Discoverer |
| Grill gate passed | Planner |
| Accepted plan, user-facing work | Designer |
| Accepted plan, not user-facing | Architect |
| Design approved | Architect |
| QA reports a design conflict | Designer, Architect, or operator |

`QA design conflict` was already routed to the Architect or operator in v1; v2 adds the
Designer when the conflict is about the approved design.

## 4. Components

### 4.1 StageRegistry

Loads and validates the stage table. Supplies the transition guard, scheduler, and
router brief with the allowed next stages. Versioned; a change to the table is a plan
amendment (v1 §5.16).

### 4.2 DiscoveryCoordinator

Launches the Discoverer with the request, repository summary, and output contract.
Collects `QuestionProposal`, `AnswerProposal`, `ResearchFinding`, and the
`DiscoveryBrief` through the controller. It never lets the Discoverer close a question.

### 4.3 QuestionLedger and GrillGate

`QuestionLedger` is an append-only projection of question events. `GrillGate` is a pure
function over the ledger and the submitted brief:

1. no blocking question is `open`;
2. every `assumed` question references a recorded user acceptance;
3. every `deferred` question has an owner and a follow-up;
4. the brief's ledger digest equals the current ledger digest.

It returns `passed` or the list of unmet conditions. A per-turn question cap and a
round cap come from configuration; reaching the round cap raises a `DecisionRequest`
to the user (proceed with assumptions, defer, or stop).

### 4.4 ResearchGateway and provenance store

```python
class ResearchGateway(Protocol):
    def search(self, query: ResearchQuery) -> tuple[ResearchSource, ...]: ...
    def fetch(self, source: ResearchSource) -> ResearchSnapshot: ...
```

The provenance store keeps snapshots (size-capped) by digest and implements the
verbatim-quote check. The gateway enforces domain allow-lists and size limits and
records every request as an effect.

### 4.5 DesignCoordinator

Launches the Designer with the brief, plan, existing design system, and user reference
images. Collects `DesignVariantSet`. Asks `RenderService` for screenshots, presents
variants to the user through the Coordinator decision path, records the selection,
launches the merge, and records approval. After a configured number of rounds without
approval it escalates to the user.

### 4.6 RenderService

```python
class RenderService(Protocol):
    def render(self, artifact: ArtifactRef,
               viewports: tuple[Viewport, ...]) -> tuple[Screenshot, ...]: ...
```

Controller-owned. Uses a browser engine with real rendering. A headless engine without
visual rendering is rejected for design evidence. A fake implementation serves tests.

### 4.7 Design binding validation

Extends the v1 issue validation (v1 §5.7). When the feature required Design, an
`IssueDraft` for user-facing work must reference at least one section of the
`DesignSpec` by stable identifier. A reference to a nonexistent section is also
rejected.

### 4.8 Tester extension

The Tester brief (v1 §5.12) gains the `DesignSpec` and approved screenshots as labeled
acceptance references. The `QAReport` gains an optional list of design differences, each
with a spec section, a viewport, and an evidence reference. Differences are evidence;
completion policy remains controller-owned.

### 4.9 SpecToolGateway

```python
class SpecToolGateway(Protocol):
    def scaffold(self, repo: RepositoryPath) -> ScaffoldResult: ...
    def new_change(self, name: ChangeName, schema: SchemaName) -> ChangeRef: ...
    def status(self, change: ChangeRef) -> ArtifactGraph: ...
    def validate(self, target: ChangeRef | SpecRef) -> ValidationResult: ...
    def show_deltas(self, change: ChangeRef) -> tuple[Delta, ...]: ...
    def archive(self, change: ChangeRef) -> ArchiveResult: ...
```

`OpenSpecCliGateway` runs the pinned binary as a child process with a fixed
environment (`OPENSPEC_TELEMETRY=0`, `DO_NOT_TRACK=1`), the repository root as working
directory, a subcommand allow-list, a timeout, an output size cap, and JSON parsing for
`status --json` and `show --json`. `scaffold`, `new_change`, and `archive` are
controller-only. Agents reach `status`, `validate`, and `show_deltas` through Milburn
commands that wrap the gateway. Results and file digests are recorded as events. A fake
gateway serves tests.

`scaffold` runs `openspec init --tools none`, installs the `milburn-spec` schema
bundle into `openspec/schemas/milburn-spec/`, and sets it as the default in
`openspec/config.yaml`.

### 4.10 Spec IDs, proposal rendering, and issue binding

OpenSpec has no numeric IDs. Milburn derives them from names:
`<capability-path>#<requirement name>` and `<capability-path>#<requirement name>#<scenario name>`.
Derivation uses the parsed deltas from `show_deltas`, rejects duplicates within a
capability, and treats a RENAMED delta as an explicit alias: on archive the controller
records the old-to-new mapping so earlier issue references still resolve.

The controller renders the approved `DiscoveryBrief` into `proposal.md` using the
`milburn-spec` proposal template (why, what changes, capabilities, impact), with the
ledger digest recorded in the change. The Architect then writes the spec deltas and
the design note.

Issue validation (v1 §5.7) is extended: an `IssueDraft` must cite at least one derived
ID that exists in the change's deltas, and a citation of a missing ID is rejected. The
Tester brief (v1 §5.12) lists the cited scenarios, and the `QAReport` maps evidence to
scenario IDs. After the Tester passes and the pull request merges, the controller calls
`archive`; until then the living specs are unchanged.

### 4.11 ActivityIngest and event envelope

Source adapters normalize into `AgentActivityEvent`:

```python
class ActivitySource(Protocol):
    name: str
    fidelity: Fidelity            # structured | session_log | environment
    def poll(self, endpoint: AgentEndpoint, cursor: SourceCursor)
        -> tuple[tuple[AgentActivityEvent, ...], SourceCursor]: ...
```

Implementations: `ExecJsonSource` (parses `codex exec --json` lines), `OtelSource` (a
local receiver or file exporter), `SessionLogSource` (version-gated parser of the
harness log), and `EnvironmentSource` (git, progress file, tests, process stats). For an
agent hosted in tmux, the controller launches Codex with a Milburn-managed home
directory per attempt, so the exporter configuration and log location are
deterministic. A source that fails or lags records `TelemetrySourceDegraded` and lowers
fidelity; it never blocks the agent.

The event envelope gains optional first-class fields so consumers can filter without
parsing facts: `feature_id`, `issue`, `attempt_id`, `generation`, `role`, `level`,
`source`, `fidelity`. The change is additive and migrated.

### 4.12 MonitorServer

A local HTTP service, bound to loopback by default, with versioned routes:

```text
GET  /v1/events?cursor=&feature=&attempt=&role=&level=   server-sent events, resumable
GET  /v1/attempts                                         current status board
GET  /v1/metrics                                          Prometheus text, off by default
POST /v1/decisions/{id}/answer                            scope: decide
POST /v1/attempts/{id}/steer | interrupt | retire         scope: steer
```

Streams read from the store by global position, so a reconnect with `Last-Event-ID`
backfills. Control routes translate to controller commands and return the controller's
verdict unchanged. Fields are filtered by scope: assistant output is sent only to
devices with `view_prose`. Non-loopback binds require TLS.

### 4.13 DevicePairing and AccessPolicy

Pairing issues a device a revocable token (stored hashed) after a one-time code or QR
exchange on the local machine. `AccessPolicy` maps tokens to scopes (`view`,
`view_prose`, `decide`, `steer`); `admin` is never granted remotely by default. `decide`
and `steer` require recent re-authentication or explicit confirmation. Every remote
request appends `RemoteActionRecorded` with the device ID. Revocation closes the
device's open streams.

### 4.14 TranscriptStore

Holds redacted assistant output, separate from the event store, keyed by attempt and
sequence, with configured retention (off, session only, or N days) enforced by a
purge job that records `TranscriptPurged`. Nothing reads it except the monitor server,
and only for devices holding `view_prose`. It has no path into handoff manifests,
defect feedback, usage records, briefs, or controller decisions. A redaction failure
drops the segment and records a marker; it never stores unredacted text.

### 4.15 Metrics, traces, and exporters

`MetricsProjection` replays events into the PRDv2 §8 metric set with a fixed label
schema. `TraceProjection` builds a trace per feature with spans for stages and
attempts. `OtlpExporter` and the Prometheus endpoint translate Milburn's versioned
schema to external names inside the exporter only, because OpenTelemetry's generative-AI
conventions are still at Development status.

### 4.16 AlertEngine and notifications

`AlertEngine` evaluates pure rules over projections and appends `AlertRaised` and
`AlertCleared`. A `NotificationProvider` interface (web push and webhook
implementations) delivers decisions and alerts to paired devices with minimal text. An
alert needing a person also becomes a `DecisionRequest` through the existing
Coordinator path (v1 §12.1).

### 4.17 LogPipeline

Structured JSON logging for the controller process with correlation IDs, levels, a
redaction filter shared with the transcript path, rotation, and retention. Logs are
diagnostics and never a source of truth.

## 5. Data contracts

```text
OpenQuestion       id, feature_id, text, category, blocking, status, resolution_ref
Assumption         id, question_id, text, accepted_decision_id
ResearchSource     id, url, kind
ResearchSnapshot   id, source_id, retrieved_at, content_digest, size, available
ResearchFinding    id, snapshot_id, quote, claim, relevance
DiscoveryBrief     id, feature_id, version, problem, users, goals, non_goals,
                   success_criteria, constraints, risks, decision_refs,
                   assumption_ids, finding_ids, ledger_digest
DesignVariant      id, set_id, screen, index, artifact_ref, screenshot_refs, rationale
DesignVariantSet   id, feature_id, screens, variants
DesignDecision     id, set_id, selection (variant or parts), decided_by_decision_id
DesignSpec         id, feature_id, version, section_ids, tokens, components, states,
                   responsive, accessibility, copy, source_decision_id, digest
StageDefinition    stage, role, required_skills, connectors, input_contract,
                   output_contract, gate, skip_policy
SpecToolPin        version, digest, platform, installed_at
ChangeRef          name, schema, path
SpecRef            capability_path
SpecItemId         capability_path, requirement, scenario (optional)
SpecIdAlias        old_id, new_id, archived_change
ValidationResult   target, ok, issues (message, location)
AgentActivityEvent id, attempt_id, generation, kind (turn, tool_call, assistant_output,
                   usage, compaction, context, retry, error), source, fidelity,
                   occurred_at, duration_ms?, tool?, command_summary?, exit_status?,
                   tokens?, context_tokens?, text_ref?, unavailable_fields
TranscriptSegment  id, attempt_id, sequence, text_ref, redaction_version, retained_until
DeviceRegistration id, label, token_hash, scopes, paired_at, last_seen, revoked_at?
AlertRule          id, condition, threshold, scope, notify
MetricDefinition   name, source_events, labels, aggregation, schema_version
```

## 6. Events

```text
DiscoveryStarted · DiscoverySkipped(authority, reason)
OpenQuestionRaised · OpenQuestionResolved(decision_ref) · QuestionWithdrawn(reason)
AssumptionAccepted(decision_ref) · QuestionDeferred(owner, followup)
ResearchRequested(effect_id) · ResearchSnapshotStored · ResearchFindingRecorded
ResearchFindingRejected(reason) · DiscoveryBriefSubmitted
GrillGatePassed · GrillGateFailed(unmet)
DesignRequiredDecided(authority) · DesignSkipped(authority, reason)
DesignVariantSetSubmitted · DesignRendered(screenshot digests)
DesignSelectionRecorded(decision_ref) · DesignApproved(decision_ref)
DesignSpecSubmitted · IssueDraftRejected(design_binding)
SpecToolPinned(version, digest) · SpecProjectScaffolded · SpecChangeCreated
SpecProposalRendered(brief_id, ledger_digest) · SpecValidated(target, ok)
IssueDraftRejected(spec_binding) · SpecArchived(change) · SpecArchiveFailed(reason)
SpecIdAliased(old, new)
AgentActivityObserved(kind, source, fidelity) · TelemetrySourceDegraded(source, reason)
TelemetrySourceRestored · TranscriptSegmentStored · TranscriptPurged(before)
DevicePaired(device) · DeviceRevoked(device) · RemoteActionRecorded(device, command)
AlertRaised(rule) · AlertCleared(rule) · NotificationSent(device, kind)
```

All use v1's event rules: append-only, idempotent identities, deterministic replay.

## 7. Skills

Role-to-skill binding (extends v1 §8.2):

| Role | Required skills |
|---|---|
| Discoverer | `milburn-discovery` |
| Designer | `milburn-design`, `frontend-design` (vendored), project design system when present |
| Architect (added) | `milburn-spec` |

`milburn-spec` carries the spec change format (requirement and scenario syntax, delta
operations), the read-only validation loop, and guardrails adapted from OpenSpec's
explore skill under the MIT notice. OpenSpec's own skills are never installed in role
workspaces.

`milburn-discovery` carries the grill procedure, the research procedure, ledger
commands, and the brief template. `milburn-design` carries the diverge and converge
procedures, variant and viewport rules, the spec template, and accessibility checks.
Precedence when guidance conflicts: project design system, then `milburn-design`, then
`frontend-design`. Vendored skills live under a reserved path with a `PROVENANCE`
record (source, commit, license, retrieved date, digest); skill validation fails if a
vendored skill lacks one.

## 8. Failure handling

| Failure | Behavior |
|---|---|
| Source unreachable or fetch times out | Snapshot recorded as `unavailable`; no finding is accepted from it |
| Quote not in snapshot | `ResearchFindingRejected`; the Discoverer is told which finding failed |
| Prompt injection in fetched text | Treated as data; findings carry quotes only; no role instruction changes |
| Brief ledger digest stale | `GrillGateFailed`; brief must be resubmitted |
| User unresponsive at a decision | Decision stays open; stage stays waiting; no assumption is made on the user's behalf |
| Render failure | `DesignRendered` not recorded; the set cannot be presented; retried with the same effect ID |
| Vendored skill digest mismatch or missing | Designer launch blocked with a clear error |
| Round caps reached | `DecisionRequest` to the user, never a silent proceed |
| Pinned OpenSpec build missing, or version or digest mismatch | Init and every spec stage fail closed with a clear error; no fallback to another build |
| `validate` reports issues | Exact messages returned to the Architect; the stage cannot pass |
| CLI timeout or crash mid-write | Change folder treated as unverified and re-validated; partial files kept for inspection |
| Network subcommand or disallowed subcommand attempted | Refused by the allow-list and recorded as a defect |
| Archive fails after merge | `SpecArchiveFailed`; retried idempotently by reconcile; never silently skipped |
| Upgrade breaks schema or parsing | The compatibility tests fail and the upgrade is blocked |
| Telemetry source down, or session-log format unrecognized | `TelemetrySourceDegraded`; fidelity drops to environment observations; the agent is not stalled |
| Ingest backlog | Sources are sampled or coalesced and the event says so; the controller never blocks on monitoring |
| Duplicate delivery to a consumer | Stable event IDs; the consumer de-duplicates |
| Redaction failure | The segment is dropped with a marker; unredacted text is never stored or sent |
| Device revoked mid-stream | The stream closes and later requests are refused |
| Remote client unreachable | Notifications queue with expiry; no controller action waits on the client |
| Clock skew between sources | Order by global position, not timestamps |

## 9. Security

The research gateway applies an egress allow-list and size and rate limits, and runs
with no credentials. Retrieved content and user reference images are stored locally
and are never sent to a role except as bounded, labeled artifacts. Vendored skills are
digest-pinned. The new roles hold no GitHub, process, or filesystem authority beyond
their own feature directory. The OpenSpec binary is pinned by digest, runs as a child
of the controller with telemetry disabled and no network need, and its output is
treated as untrusted, bounded data.

Remote monitoring adds an exposed surface. Threats and controls: stolen device token
(revocable, stored hashed, short-lived access tokens, scope limits, re-authentication
for control); secret leakage through the stream or transcripts (redaction at ingest,
`view_prose` scope, minimal notifications); network exposure (loopback by default,
TLS required elsewhere, origin checks, rate limits, no relay); and confused-deputy
control (remote commands pass the same controller policy and are audited). Tunnel
guidance, not a built-in tunnel, covers reachability.

## 10. Required tests

- Pure-policy tests for `GrillGate`: each of the four conditions failing alone, all
  passing, and a stale ledger digest.
- Ledger replay is deterministic, duplicate delivery is idempotent, and an agent
  command cannot set `answered` or `assumed`.
- Verbatim-quote check accepts exact quotes and rejects altered, truncated-and-reworded,
  and absent quotes; unavailable snapshots yield no findings.
- Stage-table validation: unknown role, missing skill, unreachable stage, cycle; the
  default table reproduces the v1 workflow.
- Skip paths: policy skip, user skip, and a skip with no recorded authority rejected.
- Design binding: an issue draft with no spec reference, a bad reference, and a valid
  reference.
- Vendored skill: digest match launches; changed, missing, or unlicensed copy blocks.
- `RenderService` contract tests with a fake; real-browser rendering as an opt-in
  contract test.
- Scripted-agent workflow from request to approved `DesignSpec` with no live model.
- `SpecToolGateway` contract tests against the fake always, and against the real pinned
  CLI as an opt-in test.
- Every CLI spawn carries the telemetry environment variables; allow-list tests reject
  apply, archive, init, and network subcommands from the agent wrapper.
- `milburn-spec` schema validates, has no `tasks` artifact and no apply block.
- ID derivation: duplicates rejected, RENAMED creates an alias, odd names handled.
- Issue binding: missing ID rejected, valid ID accepted, aliased old ID resolves.
- Archive runs only after Tester pass and merge, and not for an abandoned feature.
- Init fails on a missing or mismatched pinned build.
- Stream: ordered delivery, cursor resume, de-duplication by event ID, and per-filter
  results identical across clients.
- Ingest: each source adapter against recorded fixtures; fidelity and unavailable fields
  tagged; a degraded source records an event; terminal text never produces an event.
- Redaction fixtures with secrets in prose, commands, and paths; redaction failure drops
  the segment; retention purge honored.
- Scope matrix: `view`, `view_prose`, `decide`, and `steer` against every route;
  confirmation required for control; revoked device closes its stream; every remote
  action audited; remote commands refused with the controller's local reason.
- Pairing and token tests, including hashed storage, expiry, and replay.
- Metrics and traces replay identically; label sets contain no IDs.
- Alert rules as pure functions with positive and negative cases.
- A fake harness emitting richer events changes no consumer.
- Real Codex sources as opt-in contract tests.

## 11. Impact on v1

| v1 area | Change |
|---|---|
| ARCH §4 state machine | Becomes the default stage table (D2-1) |
| §5.3 transition guard | Reads the stage table |
| §5.4 Router | Also proposes `design_required` and discovery skip |
| §5.5 Planner | Input is the `DiscoveryBrief` |
| §5.6 Architect | Input adds the `DesignSpec`; writes the spec change; issue drafts cite design and requirement IDs |
| §5.7 issue validation | Adds design binding and spec-ID citation |
| §5.12 Tester | Brief and report gain design references and scenario mapping |
| §8 role rule system | Three new skills, vendored-skill support |
| §3.5 Workspace | The `openspec/` directory is controller-managed |
| PRD §8.2 issue content | Acceptance criteria cite scenario IDs |
| §6.1, §6.2 adapter observation boundaries | Extended to activity events and context size |
| §11 event envelope and streams | Optional first-class correlation fields; new event families |
| §15 observability | Becomes the monitor, logs, metrics, alerts, and remote design above |
| §14 security model | Remote access threats and controls |
| Usage observations (MB-017) | Add call latency and context size as optional fields |
| §10, §11 contracts, events | Additions in sections 5 and 6 above |
| §16 source tree, §17 tests | New modules and tests |

Build-task impact: MB-011 (Planner, Router, Architect), MB-007 (skill validation for
vendored skills), MB-014 (Tester), MB-015 (supervisor, alerts, reconcile), MB-016
(operator CLI and reports), and the stage-table refactor, which is cheapest to do before
the workflow code is finished.

## 12. Open questions

1. Is the stage table introduced as a v1 refactor now, or only with this increment?
2. Which headless browser serves `RenderService`, and where does it run?
3. Design artifacts: static HTML and CSS, framework components, or images only?
4. Is there a size and domain policy for research snapshots, and who edits the
   allow-list?
5. Should user reference images live in the repository or only under the Milburn home?
6. Does the Discoverer's grill procedure adapt the grilling skill used in this
   project's own build? That needs a license check first.
7. Standalone OpenSpec build or Node 22.12 or newer for the pin? The standalone build was
   not tested.
8. Name-derived requirement IDs: how robust are they to long-lived projects, and is an
   alias table enough for renames?
9. Run the CLI with an isolated config directory to guarantee its global config is never
   read or written? No stray writes were seen in testing, but the global config exists.
10. The shape of `status --json` and `show --json` is not a documented contract.
    Pin it with contract tests.
11. OpenSpec marks schema commands as experimental. What is the fallback if the schema
    format changes?
12. Does the monitor server run inside the controller process or as a separate process
    reading the store? Separate isolates remote exposure from the controller.
13. How is Codex telemetry received: a local OTLP receiver, a file exporter, or only the
    session log? None was tested here.
14. Per-attempt Codex home directories: confirm they are supported and do not break
    login.
15. Web push versus a webhook for the first notification provider.
16. Retention default and redaction rules: who maintains the secret patterns?
