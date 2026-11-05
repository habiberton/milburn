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
| discovery | Discoverer | `milburn-discovery` | research gateway (read) | request, repo summary | `DiscoveryBrief`, ledger | grill gate | policy or user |
| planning | Planner | `milburn-planning` | none | `DiscoveryBrief` | plan | plan accepted | none |
| design | Designer | `milburn-design`, `frontend-design` (vendored), project design system | render service | plan, brief, references | `DesignVariantSet`, `DesignSpec` | design approval | not user-facing, or user |
| architecture | Architect | v1 skills | none | plan, brief, `DesignSpec` | specs, issue drafts | v1 plus design binding | none |
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
```

All use v1's event rules: append-only, idempotent identities, deterministic replay.

## 7. Skills

Role-to-skill binding (extends v1 §8.2):

| Role | Required skills |
|---|---|
| Discoverer | `milburn-discovery` |
| Designer | `milburn-design`, `frontend-design` (vendored), project design system when present |

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

## 9. Security

The research gateway applies an egress allow-list and size and rate limits, and runs
with no credentials. Retrieved content and user reference images are stored locally
and are never sent to a role except as bounded, labeled artifacts. Vendored skills are
digest-pinned. The new roles hold no GitHub, process, or filesystem authority beyond
their own feature directory.

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

## 11. Impact on v1

| v1 area | Change |
|---|---|
| ARCH §4 state machine | Becomes the default stage table (D2-1) |
| §5.3 transition guard | Reads the stage table |
| §5.4 Router | Also proposes `design_required` and discovery skip |
| §5.5 Planner | Input is the `DiscoveryBrief` |
| §5.6 Architect | Input adds the `DesignSpec`; issue drafts cite it |
| §5.7 issue validation | Adds design binding |
| §5.12 Tester | Brief and report gain design references |
| §8 role rule system | Two new skills, vendored-skill support |
| §10, §11 contracts, events | Additions in sections 5 and 6 above |
| §16 source tree, §17 tests | New modules and tests |

Build-task impact: MB-011 (Planner, Router, Architect), MB-007 (skill validation for
vendored skills), MB-014 (Tester), and the stage-table refactor, which is cheapest to
do before the workflow code is finished.

## 12. Open questions

1. Is the stage table introduced as a v1 refactor now, or only with this increment?
2. Which headless browser serves `RenderService`, and where does it run?
3. Design artifacts: static HTML and CSS, framework components, or images only?
4. Is there a size and domain policy for research snapshots, and who edits the
   allow-list?
5. Should user reference images live in the repository or only under the Milburn home?
6. Does the Discoverer's grill procedure adapt the grilling skill used in this
   project's own build? That needs a license check first.
