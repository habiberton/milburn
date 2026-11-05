# MB-030 gap list

Every place where the built components did not compose, or where the slice
could not follow the approved PRD/ARCH. Each `SLICE GAP Gn` comment in
`src/milburn/app/slice.py` points here.

Status: **fixed** = fixed in this branch with a regression test. **deferred** =
recorded and worked around; it needs a decision or belongs to a deferred task.

## Gaps that need an architecture decision

| ID | Gap | Where | Spec | Status | Affects |
|---|---|---|---|---|---|
| G1 | The process model contradicts itself. `CodexAdapter.launch` runs the one-shot `codex exec --json -`. `TmuxRuntime.send_doorbell` steers by typing into a pane, which only works for an interactive TUI. A doorbell sent to an `exec` run does nothing. The slice uses the new `SubprocessCodexRuntime`, which refuses to steer. Codex offers `exec resume`, `queue`, and `app-server` as structured alternatives. | `agents/codex_adapter.py` `CodexAdapter.launch`; `runtime/tmux.py` `send_doorbell` | PRD §6.1, §10; ARCH §2.3, §7, §12 | deferred | MB-010 (Coordinator hosting), MB-015, MB-019 |
| G2 | The controller cannot record its own decisions. `ACCEPT_REQUEST`, `REQUEST_AGENT_LAUNCH`, and `REQUEST_TESTING` have intent events but no permitted actor in `_COMMAND_ACTORS`, so `Controller.handle` rejects them. `WorktreeCreated`, `CoderAttemptStarted`, `TestingRequested`, `ChangesRequested`, `IssueApproved`, and `FeatureCompleted` have no command at all. Authority policy models agent actors only. The slice appends these events directly (`SliceRunner._record`). | `domain/policies.py` `_COMMAND_ACTORS`; `orchestration/controller.py` `Controller.handle` | ARCH §3.1, §5.3, §11 | deferred | MB-013, MB-014, MB-015 |
| G4 | No production MCP client exists. `integrations/mcp` has only contracts and the journal, so `GitHubMcpGateway` and the MB-012 registry cannot reach GitHub. The slice validates the draft with the MB-012 issue contracts and records it locally as issue #1. | `integrations/mcp/`; `integrations/github/gateway.py` | PRD §8.1; ARCH §2.7, §5.7 | deferred | MB-016; the choice between MCP and `gh` |
| G6 | No component commits the Architect's specs. A Coder worktree created from the base branch therefore lacks `PRD.md` and `ARCH.md`. This also breaks the pointer-style briefs of PRD §12.4, which point at files that would not exist. The slice commits the specs to the base branch as "Milburn Controller". Where specs live (base branch, feature branch, or a PR) is part of the delivery decision. | `orchestration/architecture.py` (accepts specs and never persists them) | PRD §7, §12.4; ARCH §5.6 | deferred | delivery decision (review B1), MB-019 |
| G16 | Passed work is not delivered. The candidate stays on the local branch `milburn/issue-1`. Nothing pushes it, integrates it, or opens a PR, and a dependent issue would have no base that contains it. The slice uses a single issue so this cannot come up. | whole system | PRD §1, §5, §17; ARCH §14 | deferred | delivery decision (review Q1) |
| G17 | Rework has no attempt model. The second Coder round reuses the first attempt's worktree lease under a new launch attempt ID. | `app/slice.py` `_run` | PRD §6.2, §11; ARCH §5.14 | deferred | MB-014, MB-019 |
| G21 | A `blocked` Coder result cannot be represented. `CoderResult` requires a non-empty `commits` list for every outcome, so an honest "blocked, nothing committed" report fails parsing and the controller only sees "commits must not be empty". The live run hit this (see Live run, attempt 2). | `domain/models.py` `CoderResult.__post_init__` | PRD §9.3 ("reports blockers instead of guessing") | deferred | MB-013 (shared contract) |
| G22 | Agents commit with the user's global Git identity. The live Coder read `git config user.name` and got the operator's real name and email. Nothing sets a per-attempt identity for product agents. `ProcessLaunch` has no environment field. | `agents/codex_adapter.py` `ProcessLaunch` | ARCH §14; PRD §9.3 | deferred | MB-013 |

## Gaps fixed in this branch

| ID | Gap | Fix | Tests |
|---|---|---|---|
| G12 | The adapter passed no sandbox flag, so agents inherited the user's Codex config. On this machine that is `danger-full-access` with `approval_policy = "never"`. | `LaunchRequest.sandbox`, limited to `read-only` and `workspace-write`. The slice sets read-only for the Planner and workspace-write for the others. | `test_unknown_or_full_access_sandbox_is_rejected_before_launch`, `test_explicit_sandbox_is_passed_to_codex_exec` |
| G13 | No production Codex process runtime existed; the only real one was inside a test. | `runtime/codex_process.py` `SubprocessCodexRuntime`: stdin brief, log files, timeout, and refusal to steer. | `tests/unit/runtime/test_codex_process.py` (stub executable) |
| G14 | `GitWorktreeManager.prepare` requires `worktree_root` to exist, and nothing creates it. | The slice creates it. | covered by the scripted slice |
| G15 | `AgentResultParser.parse_jsonl` required exactly one `agent_message`. Real Codex emits progress commentary first ("I'll read the required planning skill…"), so **every live launch failed**. | The last completed agent message of the turn is the result. An earlier message is never a fallback, even when it is valid JSON. | `test_commentary_before_the_final_message_is_ignored`, `test_a_prose_final_message_is_rejected_even_after_an_earlier_valid_result` |
| G20 | A Coder in a Git worktree could not commit under `workspace-write`. Worktree metadata (index, HEAD) lives in the repository's common `.git`, outside the writable root. The live Coder wrote the code, passed its tests, and stopped at `index.lock`. | `LaunchRequest.writable_dirs` maps to `--add-dir`. The value must be absolute and requires workspace-write. Only the Coder gets the common Git directory. | `test_writable_dirs_need_workspace_write_and_absolute_paths`, `test_writable_dirs_are_passed_as_add_dir`, assertion in `test_goal_reaches_a_passed_candidate_through_every_role` |

## Gaps worked around (mechanical or minor)

| ID | Gap | Where | Status | Affects |
|---|---|---|---|---|
| G3 | The CLI has no decision round trip. The slice tells agents not to ask questions and stops on any blocking decision. | `app/slice.py` `_require_no_blocking_decisions` | deferred | MB-016 |
| G5 | The brief's result contract names the payload type but shows only `schema_version`, so agents must guess the required fields. The slice passes field templates. A schema generated from the domain models (Codex `--output-schema`) would make this mechanical. | `agents/result_parser.py` `result_contract` | deferred | MB-019 |
| G7 | MB-013's `CoderProtocolGuard` was not merged when this branch was cut. `SliceRunner._check_candidate` is a stand-in: issue, head, clean tree, issue markers, committed progress file. | `app/slice.py` | replace after MB-013 merges | MB-013 |
| G8 | `CodexAdapter.collect` returns a parsed result, but `PlannerCoordinator.accept` and `ArchitectCoordinator.accept` parse a raw document again. The slice re-serializes the result. | `orchestration/planning.py`, `architecture.py` | deferred | MB-016 |
| G9 | Skills are not installed into the agent workspace (ARCH §8.2 says copy or mount). The brief points at absolute paths in the Milburn checkout, and the agents did read them. | `agents/skill_catalog.py` | deferred | MB-007 follow-up |
| G10 | Usage observations have no event type (PRD §12 lists `AgentUsageObserved`, but `EventType` does not define it). The adapter does not extract `turn.completed.usage`. Codex's field names differ from Milburn's (`reasoning_output_tokens`, `cache_write_input_tokens`). The slice maps the fields and keeps the observations in memory. | `domain/events.py`; `agents/usage.py` | deferred | MB-016 usage report |
| G11 | Role rules, config, and skills are not packaged. The CLI finds them through the source tree or `MILBURN_ROOT`. | `app/cli.py` `_milburn_root` | deferred | MB-016 |
| G18 | Baseline context per launch: a trivial `codex exec` used 37.6k input tokens before any brief, from user config, plugins, and tools. The real launches below start at 80k or more. Per-attempt config isolation (`--ignore-user-config`, per-attempt `CODEX_HOME`) is untested. | n/a | observation | MB-019 |
| G19 | Local issue numbers always start at 1, so a second feature in local mode would collide on branch `milburn/issue-1`. | `app/slice.py` `_register_issue` | deferred | depends on G4 |
| G23 | CLI progress lines were block-buffered when output went to a file. | `app/cli.py` | fixed (flush) | none |

## Live run

Reference goal: "Add a slugify(text) function with tests." Target:
`scripts/make-slice-repo.sh`. Real Codex `codex-cli 0.166.0`, model from user
config (`gpt-6-sol`, medium).

Three live runs on 2026-11-04. No run reached the Tester yet.

| Run | Result | Gap exposed |
|---|---|---|
| 1 | Planner rejected: 2 agent messages (commentary + JSON) | G15, fixed |
| 2 | Planner ok (24s), Architect ok (51s, specs committed), Coder wrote code and passed 7 tests, but could not commit (`index.lock` outside writable root); its honest `blocked` result was then rejected | G20 fixed; G21 deferred; G22 observed |
| 3 | Planner omitted `decisions_needed` (same brief passed in run 2) | G5: needs a schema-enforced result (`--output-schema`) |

Tokens from run 2 (input / cached / output / reasoning): Planner 80,841 /
57,728 / 949 / 116; Architect 132,300 / 121,472 / 2,349 / 390; Coder 284,633 /
266,624 / 3,692 / 1,093. A trivial `codex exec` probe used 37,590 input tokens.

Live runs were paused when the product direction changed (see the review
worktree `REVIEW-2026-11-04.md`, "Direction decisions"). The slice runner is
parked as a reference; its harness fixes go to `main` separately.
