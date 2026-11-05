# Milburn

Milburn is an agent distro. You talk to one Coordinator, running in Claude Code or
Codex, which dispatches role agents (Coder, Tester, and others) into parallel Git
worktrees. The `milburn` CLI enforces what a script can check: worktree leases,
independent QA with no self-approval, journaled GitHub effects, delivery, and one
event store for token and session telemetry.

- [`PRD.md`](PRD.md): product requirements.
- [`ARCH.md`](ARCH.md): architecture.
- [`AGENTS.md`](AGENTS.md): how Milburn itself is built.

Run the tests with `scripts/run-tests.sh` and the smoke test with
`scripts/smoke-test.sh`.
