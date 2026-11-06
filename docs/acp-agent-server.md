# Role agents over ACP through the OpenHands Agent Server

Status: **paused, to resume later.**

**Decision (user, 2026-11-05).** Milburn's role agents should run as OpenHands
Agent Server conversations over ACP. Every Coder and Tester is then visible in
Agent Canvas (the user's fork is Neo, `~/projects/Neo`), with its events and
token counts while it runs. This replaces ARCH A2 (headless CLI runs) once the
sandbox question below is solved. Until then, the headless CLI adapters stay.

## What a live spike showed (2026-11-05)

Setup: Agent Server 1.60.1 behind Neo at `localhost:8000`, a host (local)
runtime, a scratch repository under the home directory, and conversations
created with `POST /api/conversations` using an `ACPAgent`.

**Session modes** (from the ACP `session/new` handshake):

| Adapter | Modes |
|---|---|
| `@agentclientprotocol/codex-acp` 2.5.0 | `read-only`, `workspace-write`, `agent` (default), `agent-full-access` |
| `@agentclientprotocol/claude-agent-acp` 0.101.0 | `default`, `acceptEdits`, `plan`, `auto` (default), `bypassPermissions` |

If a request leaves the mode unset, the Agent Server uses `bypassPermissions`
for Claude Code and `agent-full-access` for Codex. Both are full access.

**Results:**

| Check | Codex, `workspace-write` | Claude Code, `acceptEdits` + sandbox settings |
|---|---|---|
| Writes inside the worktree | allowed | allowed |
| Writes outside the worktree, and into `~/.milburn` | blocked | blocked |
| The agent asks to escape the sandbox | **escaped** | held |
| Same, with `CODEX_CONFIG={"approval_policy":"never"}` | **escaped** | n/a |
| Per-attempt Git identity, passed as conversation `secrets` | reaches the shell; Codex cannot commit (Git metadata stays read-only, as in headless runs) | commit authored as the attempt identity |
| Usage per prompt | yes | yes |

**Root cause.** In the Agent Server's ACP client,
`ACPAgent.request_permission` (`openhands/sdk/agent/acp_agent.py`, in
`software-agent-sdk`) auto-approves every permission request. A sandbox
therefore holds only when the agent cannot ask to leave it:
- **Claude Code** cannot ask, given `"sandbox": {"enabled": true,
  "allowUnsandboxedCommands": false}` in the worktree's
  `.claude/settings.local.json`. The ACP adapter honors that file.
- **Codex** asks for unsandboxed execution, and the request is approved.

**Other facts:**
- **Secrets:** they must be objects, `{"kind": "StaticSecret", "value": "..."}`.
  They reach the agent's environment, and their values show as
  `<secret-hidden>` in visible events.
- **Tags:** the request's `tags` field is free-form and stored with the
  conversation, so it can carry Milburn's work item, task, attempt, and role.
  The probe conversations were tagged `purpose=milburn-acp-spike`.
- **Results:** there is no generation-time schema flag over ACP. Milburn must
  validate the final message (`GET /api/conversations/{id}/agent_final_response`)
  after the run.
- **Errors:** turn errors are classified by their text (`UsagePolicyRefusal`,
  `ACPAuthRequired`, `ACPPromptError`). Quota exhaustion is not told apart, so
  the Coordinator judges it (ARCH §8.1).
- **Coordinator:** `parent_conversation_id` links each role agent to the
  Coordinator's conversation.

## Options considered

1. **Docker per role agent (preferred).** Run each role-agent conversation in
   its own container: `"conversation_runtime": "docker"`, with memory, CPU, and
   process limits (defaults 4 GB, 2 CPUs, 512 processes). Auto-approval then
   only reaches the container, so Codex's escape stays inside it. Nothing needs
   patching upstream.
2. **Patch the Agent Server.** Add an ACP permission policy (approve, reject,
   or reject escalations) in a fork of `software-agent-sdk`, and run Neo against
   it with `OH_AGENT_SERVER_LOCAL_PATH`. It could be offered upstream.
3. **Interim.** Run Claude Code role agents over ACP on the host, where its
   sandbox held, and keep Codex on Milburn's headless path.

## Docker plan, to try next

- **Enable it.** Restart Neo's Agent Server with per-conversation Docker
  conversations enabled (`conversation_runtime_selectable`, which needs a
  Docker daemon and `OH_SECRET_KEY`; Neo already sets the key). Check that
  `/server_info` lists `docker` in `available_conversation_runtimes`.
- **Set the environment up as config Milburn runs, not as instructions agents
  read.** The bootstrap's lesson applies (PRD R35, and §12.6 of the original
  PRD): agents do not each build their own environment. A per-project section
  in `.milburn/config.toml`, prepared and cached by Milburn before launch:

  ```toml
  [environment]
  image = "python:3.12"          # or a devcontainer / Dockerfile in the repo
  setup = ["pip install -e .[test]"]
  test = "pytest -q"
  cache = ["~/.cache/pip"]       # persisted between containers
  ```

  The brief then tells the agent only how to run the tests.
- **Use a clone per attempt, not a worktree.** A worktree's `.git` file points
  at the main repository's Git directory on the host, which the container does
  not see. A per-attempt clone lets the agent commit inside the container,
  which also removes the leftover-commit workaround (ARCH §6). Milburn fetches
  the result back. The alternative is to mount the main Git directory as well.
- **Logins in the container:**
  - Codex: the SDK already materializes `auth.json` (`acp_file_secrets`).
  - Claude Code: a subscription token passed in still needs verifying.
  - The image needs `npx` and the two ACP adapters; the stock Agent Server
    image probably has them.
- **Re-run the probes inside containers:** an escape attempt, Git identity, a
  commit inside the clone, both logins, usage events, and the final message.
- **Then build:**
  - an `agent-server` launcher in the CLI: `dispatch` creates the conversation,
    with `conversation_runtime: docker`, `parent_conversation_id`, and tags;
    `collect` reads the final response and usage over HTTP;
  - per-attempt clones;
  - the `[environment]` config.

  The CLI keeps every gate: QA independence, delivery, and the event record.
- **Costs to watch:** container start time and memory per agent, and Docker
  file-system overhead on macOS for large repositories. The caches above soften
  them.

## Cleanup still pending

- Six probe conversations tagged `purpose=milburn-acp-spike` in Neo's Canvas.
- The scratch repository at `~/.milburn-acp-spike`.

Delete both when this resumes, or before.
