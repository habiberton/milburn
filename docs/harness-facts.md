# Harness facts

Measured on 2026-11-04 against Codex 0.166.0 and Claude Code 2.1.316 on macOS.
Recorded, sanitized runs live in `tests/fixtures/harness/`. Re-check these facts
when a harness version changes; `agents/harness.py` encodes them.

## Claude Code (`claude -p`)

- **Structured result:** `--json-schema '<schema>'` works with
  `--output-format stream-json`. The final `result` event carries
  `structured_output` (the schema-checked object) and `result` (its text).
- **Isolation (PRD R37):** `--setting-sources "" --strict-mcp-config` with an
  explicit `--tools` list cut a trivial launch from about 59k to about 3.5k input
  tokens. Without `--strict-mcp-config`, claude.ai connectors load even with
  `--tools`. `--bare` cannot be used with a subscription login: it skips the
  keychain and fails with "Not logged in".
- **Sandbox:** `--settings '{"sandbox":{"enabled":true,"autoAllowBashIfSandboxed":true,"allowUnsandboxedCommands":false}}'`.
  Sandboxed Bash cannot write under the home directory ("operation not
  permitted"); it can write the working directory and temporary paths. The Write
  tool is refused outside the working directory. Commands allowed with
  `--allowedTools` still run inside the sandbox, so the event store under
  `~/.milburn` is out of reach (ARCH A3).
- **Commits from a worktree:** work once `Bash(git add:*)` and
  `Bash(git commit:*)` are allowed; `--add-dir` for the shared Git directory is
  not needed. Observed, not explained: the sandbox let `git commit` write the
  repository's shared Git directory under the home directory, while an allowed
  `touch` of another home path was blocked. So the exemption covers the
  repository's Git directory, not home paths in general; `~/.milburn` stayed
  unwritable. Re-check this with each Claude Code version. The allowance also
  permits `git commit --amend` and `-n`; the `candidate-protocol` gate checks
  the resulting commits. A compound command (`git add x && git commit`) asks for approval
  and is refused in `-p` mode, so the brief tells the Coder to run them
  separately.
- **Usage:** `result.usage` has `input_tokens` (uncached only),
  `cache_read_input_tokens`, `cache_creation_input_tokens`, `output_tokens`, and
  `output_tokens_details.thinking_tokens`. Milburn's `input_tokens` is the sum of
  the first three.
- **Rate limits:** the stream carries `rate_limit_event` with
  `rate_limit_info.status` (`allowed` observed). A refusal value has not been
  observed yet; Milburn treats `rejected` or `api_error_status: 429` as
  exhausted (ARCH §13 item 10).
- **Resume:** `--resume <session_id>`; the session ID is on every event.

## Codex (`codex exec`)

- **Structured result:** `--output-schema <file>` works with the strict schemas
  `domain/schema.py` generates.
- **Isolation:** `--ignore-user-config` works with the existing login, and drops
  the user's `danger-full-access` default. It saves little (about 18.8k to 17.9k
  input tokens for a trivial launch); most of the baseline is Codex's own prompt.
  It also drops the configured model, so pass `--model` when a role needs one.
- **Usage:** `turn.completed.usage` has `input_tokens`, `cached_input_tokens`,
  `cache_write_input_tokens`, `output_tokens`, `reasoning_output_tokens`.
- **Git under workspace-write:** the sandbox keeps Git metadata read-only,
  including a worktree's resolved gitdir, even when it is passed with
  `--add-dir`. `git add` failed with "Unable to create '.../.git/worktrees/t1/index.lock':
  Operation not permitted" in a live run. A Codex Coder cannot commit; Milburn
  commits for it at collect (ARCH §6).
- **Errors:** `error` and `turn.failed` events carry prose, not a stable code, so
  Milburn classifies them as `unknown` and the Coordinator decides (ARCH §8.1).
- **Resume:** `codex exec resume [options] <session_id> -`; the session ID is the
  `thread.started` event's `thread_id`.
