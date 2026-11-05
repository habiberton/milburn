# Milburn Product Requirements Document v2 (draft additions)

**Status:** Draft. Not approved. Does not change `PRD.md` or any build task.

**Relationship to v1:** This document adds requirements to `PRD.md` (v1). v1 stays
authoritative for everything not named here. Section references like "v1 §6" mean
`PRD.md`. Where this document and v1 conflict, stop and ask the user; do not choose.
Requirement IDs here start with `V2-`.

**Harness:** Codex first, as in v1. Nothing in this increment needs another harness.

## 1. Intent

v1 starts at a plan. A software factory should start earlier, at the idea, and
should settle how a user-facing product looks before it is coded. This increment adds
two stages ahead of the Architect:

1. **Discovery**, which gathers evidence and interrogates the idea until nothing
   blocking is left open (the **grill gate**).
2. **Design**, which produces several visual variants of each user-facing screen or
   flow, converges on one with the user, and hands a binding design spec to the
   Architect and later to the Tester.

Both follow v1's authority rule: agents propose and produce artifacts; the
deterministic controller decides whether a gate is passed.

## 2. Workflow change

```text
User request in Coordinator chat
    ↓
Coordinator submits a bounded intake proposal
    ↓
Router proposes next stage (discovery required? design required?)
    ↓
DISCOVERY   Discoverer researches, raises questions, user answers
            → DiscoveryBrief          ── grill gate ──
    ↓
PLANNING    Planner plans from the DiscoveryBrief            (v1)
    ↓
DESIGN      (user-facing work only) Designer produces N variants
            → user converges → DesignSpec        ── design approval ──
    ↓
ARCHITECTURE  Architect writes the target PRD.md and ARCH.md, the spec change
              (requirements with scenarios, design note), and issue drafts
              that cite the DesignSpec and the requirement IDs  (v1, extended)
    ↓
… Coder → Tester → done                                       (v1)
```

Discovery and Design can each be skipped, but only by recorded policy or a recorded
user decision (V2-22 for Discovery, V2-8 for Design).

## 3. Roles

| Role | New | Responsibility | Product-code writes | Output |
|---|---|---|---:|---|
| Discoverer | yes | Research the idea, raise and track questions, draft the brief. | No | `DiscoveryBrief`, research findings, question proposals |
| Designer | yes | Produce design variants, merge the user's selection, write the design spec. | Design artifacts only | `DesignVariantSet`, `DesignSpec` |
| Planner | changed | Plans from the approved `DiscoveryBrief`, not only the raw request. | No | Plan |
| Architect | changed | Receives the brief and design spec; writes the spec change; issue drafts cite the design spec and requirement IDs. | Docs only | Specs, spec change, and issue drafts |
| Tester | changed | Receives the design spec and approved screenshots as acceptance references. | No by default | QA report |

The role names are provisional (open question 1). The Discoverer and Designer follow
every v1 role rule: one bounded role, own tmux window, cannot launch peers, cannot
mutate GitHub, cannot approve its own gate.

## 4. Discovery stage and the grill gate

### 4.1 Discovery brief

The `DiscoveryBrief` is the stage's output and is separate from the target product's
`PRD.md`, which the Architect still writes. It records:

- the problem and the users it affects,
- goals, non-goals, and measurable success criteria,
- constraints and risks,
- decisions, each tied to a recorded user decision,
- assumptions, each tied to a recorded user acceptance,
- the evidence it relies on, as references to recorded research findings,
- the question ledger state (V2-2) at the time of submission.

### 4.2 Question ledger

Every unresolved matter is an `OpenQuestion` held in a controller-owned ledger. A
question has an identity, text, category, whether it is blocking, and a status:
`open`, `answered`, `assumed`, `deferred`, or `withdrawn`.

- **V2-1. Explore before asking.** The Discoverer must answer from the repository, the
  request, and recorded research whatever those can answer. It asks the user only for
  decisions and facts it cannot find, and it records what it checked.
- **V2-2. The controller owns the ledger.** The Discoverer proposes questions and
  proposed answers. Only a recorded user decision moves a question to `answered` or
  `assumed`. A question the Discoverer withdraws stays visible with its stated reason.
- **V2-3. Grill gate.** Discovery completes only when all of these hold:
  1. no blocking question is `open`;
  2. every `assumed` question has a recorded user acceptance;
  3. every `deferred` question names an owner and a follow-up;
  4. the submitted brief's ledger digest matches the current ledger.

  The gate is evaluated by controller policy, never by the Discoverer. A failed gate
  returns to the Discoverer with the unmet conditions.
- **V2-4. Bounded interrogation.** The Coordinator presents at most a configured
  number of questions per turn, and after a configured number of rounds the controller
  asks the user whether to proceed with recorded assumptions, defer, or stop. The
  grilling cannot continue indefinitely.

### 4.3 Research

- **V2-5. Read-only, controller-owned research.** Web search, page fetch, and
  repository reading go through a controller-owned research gateway with an
  allow-list, like the GitHub gateway in v1 §8.1. Research tools have no mutation
  authority and no credentials the agent can read.
- **V2-6. Provenance.** Every finding records its source, retrieval time, a digest of
  the stored content snapshot, and a verbatim quote. The controller rejects a finding
  whose quote does not appear in its snapshot. An unreachable source is recorded as
  unavailable, never filled in.
- **V2-7. Fetched content is untrusted.** Retrieved text is data. It cannot grant
  permissions, change instructions, or trigger a tool call. Findings are structured
  records, and snapshots are stored as bounded artifacts, not pasted into other
  agents' briefs wholesale.

### 4.4 Skipping discovery

- **V2-22. Discovery is required unless skipped on the record.** It is required for a
  new feature or product. It may be skipped when the Router classifies the work as a
  bug fix or chore and controller policy allows that, or when the user decides to skip
  it. Either way the skip, its reason, and its authority are recorded events. A skipped
  discovery produces a minimal brief that states what was skipped.

## 5. Design stage

- **V2-8. Applicability.** The Router proposes whether work is user-facing. Controller
  policy confirms it. The user can override either way, and the override is recorded.
  Work that is not user-facing skips Design.
- **V2-9. Diverge.** For each designated screen or flow the Designer produces a
  configured number of variants (default four, allowed two to six). Each variant is a
  self-contained renderable artifact plus a controller-rendered screenshot at the
  configured viewports (at least one narrow and one wide) and a short rationale.
  Reference images the user supplies ("make it feel like this") are stored as
  artifacts and cited by the variants that use them.
- **V2-10. Converge.** The user chooses a variant or selects parts of several. The
  Designer merges them into one candidate, and the user approves it. Selection and
  approval are recorded user decisions. After a configured number of rounds without
  approval the controller escalates to the user (the v1 rework-convergence idea, §12.5).
- **V2-11. Design spec.** The approved result is a `DesignSpec`, committed with the
  feature: design tokens, components, every state each component needs (empty,
  loading, error, hover, focus, disabled), responsive behavior, accessibility
  requirements (contrast, keyboard operation, focus order, labels), and copy.
- **V2-12. Binding.** When Design is required, the controller rejects an Architect
  issue draft for user-facing work that cites no part of the `DesignSpec`. The Tester
  receives the spec and the approved screenshots as acceptance references and records
  differences as evidence. No automatic pixel-diff gate is required in this
  increment; the Tester supplies evidence and controller policy decides, as in v1.
- **V2-13. Rendering is controller-owned.** Screenshots come from a controller-owned
  rendering service that uses a browser engine with real visual rendering. A browser
  without rendering is not acceptable for design evidence.

## 6. Living specs and change folders

v1 writes `PRD.md` and `ARCH.md` once and says nothing about how they evolve, and
acceptance criteria live only inside issue bodies. This increment adopts the file
layout and validation of [OpenSpec](https://github.com/Fission-AI/OpenSpec), an open
source (MIT) spec-driven tool, for the **target repository's** specs. Milburn calls a
pinned copy of its CLI under controller ownership. Milburn does not fork it; every
difference is expressed as a project schema, configuration, or a wrapper.

Facts checked against OpenSpec 1.16.0: MIT licensed; needs Node 22.12 or newer, or
its standalone build; the CLI works offline and writes only into the project;
telemetry is on by default and is disabled with `OPENSPEC_TELEMETRY=0` or
`DO_NOT_TRACK=1`; requirements are headed `### Requirement: <name>` and scenarios
`#### Scenario: <name>`; there are no numeric IDs.

- **V2-23. Layout.** The target repository keeps its living specs under
  `openspec/specs/<capability>/spec.md`. Each feature is a change folder under
  `openspec/changes/<name>/` holding the proposal, the requirement deltas
  (ADDED, MODIFIED, REMOVED, RENAMED), and a design note. The controller validates
  both.
- **V2-24. The brief is the proposal.** The approved `DiscoveryBrief` becomes the
  change's `proposal.md`, generated by the controller from the brief. The question
  ledger stays Milburn state beside it.
- **V2-25. Each document has one job.** `PRD.md` is the product narrative (why and
  what). The specs are the testable requirements. `ARCH.md` is how. A document
  cites another and never restates it.
- **V2-26. Scenarios are acceptance criteria.** Every requirement has at least one
  scenario. Milburn derives a stable ID from names (`<capability>#<requirement>` and
  `<capability>#<requirement>#<scenario>`), rejects duplicates, and records renames
  explicitly. Issue drafts must cite the IDs they implement, and the Tester maps its
  evidence to scenarios.
- **V2-27. The controller owns the tool.** `milburn init` installs or verifies a
  pinned OpenSpec build, records its version and digest, and scaffolds with
  `--tools none`. Only the controller, and a read-only command wrapper for agents
  (validate, show, status), invokes the CLI. Every invocation disables telemetry,
  and subcommands that contact the network (the update check and feedback) are never
  called.
- **V2-28. Milburn's schema.** Milburn ships a project schema `milburn-spec` in
  `openspec/schemas/`, forked from OpenSpec's `spec-driven` schema with the `tasks`
  artifact and the apply step removed: proposal, then specs and design. Tasks are
  GitHub issues (v1 §8), so there is one task list.
- **V2-29. No OpenSpec skills in role workspaces.** OpenSpec's own skills, including
  the one that implements tasks, are not installed for any role. Agents use the
  Milburn-owned `milburn-spec` skill (section 7). No agent can run apply, archive, or
  init.
- **V2-30. Archive after proof.** The controller archives a change into the living
  specs only after the Tester passes and the pull request is merged. An abandoned or
  failed feature leaves its change folder unarchived and the living specs unchanged.
- **V2-31. Pinned, attributed, tested upgrades.** Adapted OpenSpec text keeps the MIT
  notice. Changing the pinned version requires passing Milburn's compatibility tests
  (schema validation, delta parsing, ID derivation), because OpenSpec's workflow and
  command names have changed between versions and its schema commands are marked
  experimental.

## 7. Skills

v1 ships six role skills (§13.1). This increment adds three Milburn-owned skills and a
policy for third-party skills.

- **V2-14. `milburn-discovery`.** The grill procedure (explore first, one decision at
  a time, recommend an answer for each question), research procedure, ledger commands,
  and the brief template.
- **V2-15. `milburn-design`.** The diverge and converge procedures, variant and
  viewport rules, the design-spec template, and accessibility checks.
- **V2-32. `milburn-spec`.** How to write the spec change in OpenSpec's format,
  including the requirement and scenario syntax, delta operations, and the read-only
  validation loop. It adapts guardrails from OpenSpec's explore skill (ask before
  writing; thinking is not implementing) under the MIT notice.
- **V2-16. Third-party skills are vendored and pinned.** Anthropic's `frontend-design`
  skill may be used for the Designer. Milburn does not fetch it at launch. A pinned
  copy lives in the repository with its upstream license text, upstream source and
  commit, retrieval date, and digest. Every launch records the digest, and a changed
  or missing copy blocks launch (v1 §13.1 rule). Before vendoring, the upstream
  `LICENSE.txt` must be read and its terms confirmed to allow redistribution
  (open question 5).
- **V2-17. Precedence.** A project's own design-system skill outranks `milburn-design`,
  which outranks `frontend-design`. The last guides greenfield work and projects with
  no design system. Skills guide judgment and never grant authority (v1 §13.1).
- **V2-18. Skill format.** Skills use the open `SKILL.md` Agent Skills format, which
  Codex and Claude Code both read, so an Anthropic skill needs no conversion.

## 8. Observability and remote monitoring

v1 records events and token usage (§12.1) but defines no live stream, logs, metrics, or
remote view. This increment adds them. Codex owns each agent's model-and-tool loop, so
what Milburn can see of an agent's activity depends on what Codex exposes. A future
custom harness owns its loop and can report more. The design must work with the first
and not change for the second.

- **V2-33. One spine.** The durable event store is the only source. The live stream,
  log views, metrics, and traces are projections or exports of it. Monitoring holds no
  state of its own, so replay after restart rebuilds all of it.
- **V2-34. Live stream.** Events are delivered in global order, are resumable from a
  cursor, are delivered at least once with stable event IDs for de-duplication, and
  backfill from the store after a disconnect. Consumers can filter by feature, issue,
  attempt, role, and level. The command line, the terminal board, and the remote
  interface all read the same stream.
- **V2-35. Agent activity events.** A family of `AgentActivityObserved` events records
  what an agent does between checkpoints: turns, tool calls (tool, command summary,
  exit status, duration), assistant output, usage, compaction, context size, retries,
  and errors. Each event names its source and fidelity. Missing detail stays explicitly
  unavailable and is never inferred.
- **V2-36. Source fidelity order.** Milburn prefers, in order: a structured stream or
  telemetry the harness exposes; the harness's session log (version-gated, since its
  format is not a documented contract); and observations of the environment that need
  no harness cooperation (commits, progress file changes, test runs, process liveness,
  CPU and memory). Terminal text is for human viewing only and is never evidence.
- **V2-37. Assistant output.** Assistant prose is shown in the stream when the harness
  provides it. It is classified sensitive, passes through secret redaction before it is
  streamed or stored, and is kept in a transcript store separate from the event store,
  with a configured retention (off, session only, or retained for a set number of days).
  It is never copied into a handoff manifest, defect feedback, usage records, or any
  input to a controller decision, and it is never treated as evidence. Hidden reasoning
  is not captured; only output the harness presents as visible is shown. This relaxes
  v1's wording on transcripts for display purposes only (open question 13).
- **V2-38. Logs.** The controller writes structured logs with levels, correlation IDs
  (feature, issue, attempt, generation, effect), redaction, rotation, and retention.
  Events are durable facts; logs are diagnostics and may be dropped. Command output
  stays in referenced log files (v1 §12.6).
- **V2-39. Metrics.** Metrics derive deterministically from events. They cover flow
  time per stage and gate, launch-to-first-activity, attempt duration, effect latency
  and uncertain-effect rate, rework rounds and escalation rate, first-attempt QA pass
  rate, tokens by role, model, and attempt (including cache-hit ratio, launch context
  size, peak context, compactions, and replacements), and counts of unknown, stopped,
  and failed attempts. Labels are low-cardinality (role, stage, model, outcome); task
  and attempt IDs appear on events and traces, not as metric labels. Pricing and
  budgets remain out of scope (v1 §5).
- **V2-40. Traces.** A feature is a trace, and its stages and attempts are spans,
  built from events after the fact. No live instrumentation of agents is required.
- **V2-41. Optional export.** An OTLP exporter and a Prometheus-format endpoint are
  available and off by default. Milburn's own event schema is versioned independently
  of OpenTelemetry's generative-AI conventions, which are still at Development status,
  and is mapped only inside the exporter.
- **V2-42. Alerts.** Alerts are events produced by deterministic rules: an attempt idle
  too long, no commits for too long, context above a threshold, non-converging
  rework, a backlog of uncertain effects, and a telemetry source down. An alert needing
  a person reaches them through the Coordinator decision path and as a push
  notification.
- **V2-43. Remote and phone access.** Milburn serves an authenticated, TLS-protected
  monitoring interface that works on a phone. It binds to the local machine by default.
  Remote access is an explicit opt-in through a secure tunnel or private network that
  the user provisions. Milburn requires no hosted relay and runs none.
- **V2-44. Device pairing and scopes.** Each remote device is paired and holds a
  revocable token. Scopes are `view`, `view_prose` (assistant output), `decide`
  (answer decisions), and `steer` (steer, interrupt, retire). `admin` is never granted
  remotely by default. A `decide` or `steer` action needs recent re-authentication or
  explicit confirmation. Every remote action is an audited event naming the device, and
  the controller validates every remote command exactly as it validates a local one.
  Remote access never bypasses controller authority.
- **V2-45. Phone notifications.** Decisions and alerts are pushed to paired devices
  through a configurable provider. Notification text is minimal and carries no
  assistant output or secrets by default.
- **V2-46. Harness-neutral vocabulary.** The activity vocabulary has optional fields so
  a harness that owns its loop can emit the same events natively and add per-call
  latency, retries, tool timing, and exact usage. Nothing downstream changes.
- **V2-47. Monitoring never blocks work.** Ingest pressure or a failing source lowers
  fidelity and records an event. It never stalls an agent or the controller.

## 9. Cross-cutting requirements

- **V2-19. Declarative stages.** The sequence of stages is defined as data (role,
  required skills, allowed connectors, input and output contracts, gate, and skip
  policy), and the transition guard enforces it. Discovery and Design are table
  entries. v1's behavior is the default table. This is the one structural change the
  increment needs from v1 (ARCHv2 §2).
- **V2-20. v1 disciplines apply.** Fresh launches, bounded briefs with digests,
  context thresholds (v1 §12.4), bounded command output (§12.6), token telemetry
  (§12.1), and durable handoff (§12.2) apply to both new roles without exception.
- **V2-21. No new authority.** Neither new role gets GitHub mutation, process
  control, or the ability to pass its own gate.

## 10. Acceptance criteria (additions)

The increment is accepted when:

1. A request that needs discovery cannot reach planning until the grill gate passes,
   and the gate rejects an open blocking question, an unaccepted assumption, a
   deferred question with no owner, and a brief whose ledger digest is stale.
2. A Discoverer cannot mark a question answered or assumed; only a recorded user
   decision can.
3. The Discoverer answers repository-answerable questions without asking the user,
   and records what it checked.
4. A research finding whose quote is absent from its stored snapshot is rejected, and
   an unreachable source is recorded as unavailable.
5. Retrieved text cannot change a role's instructions, permissions, or tools.
6. A user-facing feature produces the configured number of variants, each rendered at
   the required viewports by the controller's rendering service.
7. The user's selection and approval are recorded decisions, and the merged design
   becomes a committed `DesignSpec`.
8. An issue draft for user-facing work with no `DesignSpec` reference is rejected, and
   the Tester receives the spec and approved screenshots as references.
9. A feature that is not user-facing skips Design, and a skip of either stage by
   policy or by the user is recorded with its authority.
10. The vendored `frontend-design` copy launches only when its digest matches; a
    changed, missing, or unlicensed copy blocks launch with a clear error.
11. A project design-system skill takes precedence over `frontend-design`.
12. Adding a stage to the stage table needs no change to controller core, and the v1
    workflow is reproduced exactly by the default table.
13. Replay of the question ledger and design decisions after restart produces the same
    state; duplicate delivery is idempotent.
14. `milburn init` installs or verifies the pinned OpenSpec build, records its version and
    digest, scaffolds with no vendor skills, and installs the `milburn-spec` schema;
    a missing or mismatched build fails with a clear error.
15. Every OpenSpec invocation by Milburn runs with telemetry disabled, and no
    network-contacting subcommand is ever called.
16. The approved brief appears as the change's proposal and carries the ledger digest.
17. Validation rejects a requirement with no scenario and a change with no deltas
    (unless declared as touching no behavior); an issue draft citing a missing
    requirement or scenario ID is rejected.
18. Living specs are unchanged until the Tester passes and the pull request merges;
    only then does the controller archive the change.
19. Role workspaces contain no OpenSpec skills, and an agent cannot run apply, archive,
    init, or any subcommand outside the read-only set.
20. Changing the pinned OpenSpec version runs the compatibility tests, and a failure
    blocks the change.
21. The live stream is ordered, resumes from a cursor after disconnect without loss or
    duplication visible to a de-duplicating consumer, and applies the same filters on
    every client.
22. Activity events carry source and fidelity, show missing detail as unavailable, and
    are never derived from terminal text.
23. Assistant output is redacted before it is streamed or stored, honors the configured
    retention, is absent from handoffs, feedback, usage, and decision inputs, and
    appears only for devices holding `view_prose`.
24. Metrics replay identically after restart and use only low-cardinality labels; the
    usage metrics include launch context size, cache-hit ratio, and compaction counts.
25. Each alert rule fires on its condition and not otherwise, and an alert needing a
    person arrives through the Coordinator decision path and a push notification.
26. Remote access is off until enabled, requires TLS for any non-local address, and
    needs no hosted relay.
27. A device with `view` cannot answer a decision or steer; a `decide` or `steer` action
    without recent re-authentication or confirmation is refused; every remote action
    is an audited event with the device ID; a revoked device's stream closes.
28. A remote command that the controller would refuse locally is refused remotely with
    the same reason.
29. A failing telemetry source or an overloaded ingest records a degraded-fidelity event
    and does not stall any agent.
30. Replacing the harness with a fake that emits richer events changes no consumer.

## 11. Not in this increment

Persona-based user testing, a bug-intake loop from monitoring, parallel Coders,
LLM-judge scoring of plans and specs, per-agent computers, inboxes, or phones,
automatic deploy, additional harnesses, forking OpenSpec, importing an existing
OpenSpec project, OpenSpec's own apply and verify workflows, a hosted relay, multi-user
access control, pricing and budgets, and any use of captured assistant output as
handoff, feedback, or evidence input. They are candidates for later increments.

## 12. Open questions

1. Role names: separate `Discoverer` and `Designer`, or fold discovery into the
   Planner and design into the Architect with new skills?
2. Does Design run before the Architect (as drafted) or after, once architecture
   constraints are known?
3. Design artifact format: static HTML and CSS, framework components, or images only?
4. Where does the rendering service run, and which browser engine?
5. License confirmation for `frontend-design` (the evidence found points to Apache-2.0
   but the upstream `LICENSE.txt` was not read) and for any skill content adapted
   from the grilling skill used during this project's own build. OpenSpec itself is
   confirmed MIT (1.16.0).
6. Defaults for the question budget per turn, rounds before escalation, variant count,
   and viewports.
7. How are user reference images stored and kept private?
8. How does this document merge into `PRD.md`: replace v1 sections, append, or ship as
   a numbered release?
9. Does the Milburn-owned `milburn-spec` schema stay OpenSpec-compatible enough that a
   user's existing OpenSpec project can be adopted later?
10. Is the standalone OpenSpec build acceptable for the pin, or should `milburn init`
    require Node 22.12 or newer?
11. Requirement IDs derive from names. How are renames across a long-lived project
    tracked so references from old issues keep resolving?
12. OpenSpec's schema commands are experimental. What is the fallback if its schema
    format changes?
13. v1 lists copying private transcripts as a non-goal and says feedback holds no
    transcript. V2-37 allows displaying and retaining assistant output under controls.
    Should the v1 wording be amended when these documents merge?
14. Default retention for the transcript store, and whether the default is off.
15. Push provider: web push, a webhook to a notification service, or both?
16. Recommended tunnel or private-network setup for remote access, and how pairing is
    done on a phone (code, QR, passkey).
17. How does Milburn receive Codex telemetry: a local OTLP receiver, a file exporter, or
    only the session log? None was tested.
18. Is the harness's session log stable enough to rely on, and what is the support
    policy when its format changes?
